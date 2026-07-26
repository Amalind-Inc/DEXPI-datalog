#!/usr/bin/env bash
# Prepare a fresh Oracle Cloud VM.Standard.E2.1.Micro (Ubuntu) to run PortLog.
#
# Run once, as the `ubuntu` user, on a box with nothing else on it. It is
# idempotent: re-running skips work that is already done rather than failing.
#
# It stops short of starting the app, because that needs secrets a script
# should not invent. It prints the remaining steps at the end.
#
#   curl -fsSL https://raw.githubusercontent.com/Harborfield-suite/PortLog/main/scripts/bootstrap-oci.sh | bash
#
set -euo pipefail

say() { printf '\n=== %s\n' "$1"; }

if [ "$(uname -m)" != "x86_64" ]; then
  echo "FAIL: this is $(uname -m); PortLog needs x86_64." >&2
  echo "The Ampere/A1.Flex shape cannot run it -- Souffle publishes no arm64" >&2
  echo "binary. Recreate the instance as VM.Standard.E2.1.Micro." >&2
  exit 1
fi

say "1/5 swap"
# The stack peaks near 850 MiB of the 1024 this shape has. Without swap a
# spike is resolved by the kernel OOM killer, which has a habit of choosing
# sshd -- locking you out of the machine you are deploying to.
if swapon --show | grep -q /swapfile; then
  echo "  already on"
else
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile >/dev/null
  sudo swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
  echo "  2G added and recorded in /etc/fstab"
fi
free -h | sed 's/^/  /'

say "2/5 local firewall"
# Opening 80/443 in the VCN security list is only half of it. The Oracle
# Ubuntu image also ships iptables rules that drop everything except SSH, so
# without this Caddy cannot answer the ACME challenge and certificate issuance
# hangs with no useful error.
sudo apt-get update -qq
sudo apt-get install -y -qq iptables-persistent netfilter-persistent >/dev/null 2>&1 || true
for port in 80 443; do
  if sudo iptables -C INPUT -m state --state NEW -p tcp --dport "$port" -j ACCEPT 2>/dev/null; then
    echo "  $port already accepted"
  else
    sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport "$port" -j ACCEPT
    echo "  $port opened"
  fi
done
sudo netfilter-persistent save >/dev/null
echo "  saved across reboot"

say "3/5 docker"
if command -v docker >/dev/null 2>&1; then
  echo "  already installed: $(docker --version)"
else
  sudo apt-get install -y -qq ca-certificates curl git >/dev/null
  sudo install -m 0755 -d /etc/apt/keyrings
  sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  sudo chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update -qq
  sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null
  sudo usermod -aG docker "$USER"
  echo "  installed: $(docker --version)"
  echo "  NOTE: group membership needs a new login -- log out and back in,"
  echo "        or prefix docker commands with sudo until you do."
fi

say "4/5 source"
if [ -d "$HOME/PortLog/.git" ]; then
  git -C "$HOME/PortLog" pull --ff-only
  echo "  updated"
else
  git clone --recurse-submodules https://github.com/Harborfield-suite/PortLog.git "$HOME/PortLog"
  echo "  cloned"
fi

say "5/5 .env skeleton"
ENV_FILE="$HOME/PortLog/.env"
if [ -f "$ENV_FILE" ]; then
  echo "  $ENV_FILE exists -- left alone, secrets not regenerated"
else
  # Generated once and kept. Regenerating these later invalidates every
  # session and makes every stored model key undecryptable, so the file is
  # never overwritten above.
  cat > "$ENV_FILE" <<EOF
HARBORFIELD_PUBLIC_HOST=harborfield.live
BETTER_AUTH_URL=https://harborfield.live
TLS_CONTACT_EMAIL=CHANGEME@harborfield.live

MINIO_ROOT_USER=portlogadmin
MINIO_ROOT_PASSWORD=$(openssl rand -base64 32)
BETTER_AUTH_SECRET=$(openssl rand -base64 32)
HARBORFIELD_BYOK_SECRET=$(openssl rand -base64 32)

SMTP_HOST=smtp-relay.brevo.com
SMTP_PORT=587
SMTP_FROM=portlog@harborfield.live
SMTP_USER=CHANGEME
SMTP_PASSWORD=CHANGEME
EOF
  chmod 600 "$ENV_FILE"
  echo "  written with fresh secrets, mode 600"
fi

cat <<'NEXT'

=== Done. Three things left, in this order.

1. Fill in the placeholders:

     nano ~/PortLog/.env

   TLS_CONTACT_EMAIL, SMTP_USER, SMTP_PASSWORD.
   SMTP credentials: Brevo -> SMTP & API -> SMTP tab.
   The password is the SMTP key, not your Brevo account password.

2. Confirm DNS resolves to this machine before starting, or Let's Encrypt
   will fail the challenge:

     dig +short harborfield.live
     curl -s ifconfig.me; echo

   Those two must match.

3. Start it:

     cd ~/PortLog
     export PORTLOG_IMAGE_TAG=latest
     docker compose -f docker-compose.yml -f docker-compose.prod.yml \
       -f docker-compose.micro.yml -f docker-compose.pull.yml up -d --pull always

   Then watch the certificate arrive:

     docker compose logs -f proxy

NEXT
