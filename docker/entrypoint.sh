#!/usr/bin/env bash
#
# Bring up the hosted profile: secrets, bucket, schema, then both processes.
#
# The work here is the difference between a quickstart that works and one that
# needs a person who already knows the system. Everything it does by hand is
# something the README used to ask you to do.

set -euo pipefail

STATE_DIR="${PYDEXPI_STATE_DIR:-/data}"

# A hosted instance that cannot write its state directory would come up looking
# healthy and lose every account on restart. Refuse instead.
if ! mkdir -p "${STATE_DIR}" 2>/dev/null || [ ! -w "${STATE_DIR}" ]; then
  echo "FATAL: ${STATE_DIR} is not writable." >&2
  echo "Accounts and secrets live there. Mount a volume on it:" >&2
  echo "  docker run -v pydexpi-data:${STATE_DIR} ..." >&2
  exit 1
fi

# --- Secrets -----------------------------------------------------------------
# Generated once and kept, because both of these encrypt data at rest. A fresh
# BETTER_AUTH_SECRET invalidates every session; a fresh PYDEXPI_BYOK_SECRET
# makes every saved model credential undecryptable. Generating them per boot
# would be silent data loss, so they persist and are only created when absent.
secret_file="${STATE_DIR}/secrets.env"
if [ ! -f "${secret_file}" ]; then
  umask 077
  {
    echo "BETTER_AUTH_SECRET=$(openssl rand -base64 32)"
    echo "PYDEXPI_BYOK_SECRET=$(openssl rand -base64 32)"
  } > "${secret_file}"
  echo "generated ${secret_file} (keep it: it decrypts saved model keys)"
fi

# Environment wins, so a real deployment can supply its own from a secret
# manager and never use the generated file.
# shellcheck disable=SC1090
set -a; source "${secret_file}"; set +a
export BETTER_AUTH_SECRET PYDEXPI_BYOK_SECRET

export BETTER_AUTH_URL="${BETTER_AUTH_URL:-http://localhost:3000}"
export PYDEXPI_AUTH_DB="${PYDEXPI_AUTH_DB:-${STATE_DIR}/auth.sqlite3}"
export PYDEXPI_REVIEW_API_URL="${PYDEXPI_REVIEW_API_URL:-http://127.0.0.1:8000}"

# The three OIDC settings must agree with BETTER_AUTH_URL: the backend verifies
# tokens the front end issues, so a mismatch means every request is a 401.
export PYDEXPI_OIDC_ISSUER="${PYDEXPI_OIDC_ISSUER:-${BETTER_AUTH_URL}}"
export PYDEXPI_OIDC_AUDIENCE="${PYDEXPI_OIDC_AUDIENCE:-${BETTER_AUTH_URL}}"
export PYDEXPI_OIDC_JWKS_URL="${PYDEXPI_OIDC_JWKS_URL:-${BETTER_AUTH_URL}/api/auth/jwks}"

# --- Wait for the backing services -------------------------------------------
# Compose's `depends_on` waits for a container, not for a database that answers.
wait_for() {
  local name="$1" url="$2" tries=60
  until curl --silent --output /dev/null --max-time 2 "${url}" || [ "${tries}" -eq 0 ]; do
    tries=$((tries - 1))
    [ "${tries}" -eq 30 ] && echo "still waiting for ${name} at ${url}..."
    sleep 1
  done
  if [ "${tries}" -eq 0 ]; then
    echo "FATAL: ${name} never answered at ${url}" >&2
    exit 1
  fi
}

if [ -n "${PYDEXPI_LIBSQL_URL:-}" ]; then
  wait_for "libSQL" "${PYDEXPI_LIBSQL_URL}"
fi

# --- Bucket ------------------------------------------------------------------
# Creating it here rather than in the README is the point: an object store that
# exists but has no bucket fails at the first upload, long after startup.
if [ -n "${PYDEXPI_S3_ENDPOINT_URL:-}" ] && [ -n "${PYDEXPI_S3_BUCKET:-}" ]; then
  wait_for "object storage" "${PYDEXPI_S3_ENDPOINT_URL}/minio/health/live"
  python - <<'PY'
import os
import sys

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

bucket = os.environ["PYDEXPI_S3_BUCKET"]
client = boto3.client(
    "s3",
    endpoint_url=os.environ["PYDEXPI_S3_ENDPOINT_URL"],
    aws_access_key_id=os.environ.get("PYDEXPI_S3_ACCESS_KEY_ID") or None,
    aws_secret_access_key=os.environ.get("PYDEXPI_S3_SECRET_ACCESS_KEY") or None,
    region_name=os.environ.get("PYDEXPI_S3_REGION", "us-east-1"),
    # MinIO has no DNS for virtual-hosted buckets.
    config=Config(s3={"addressing_style": "path"}),
)

try:
    client.head_bucket(Bucket=bucket)
    print(f"bucket {bucket} is present")
except ClientError:
    try:
        client.create_bucket(Bucket=bucket)
        print(f"created bucket {bucket}")
    except ClientError as error:
        # A managed bucket may exist but refuse head_bucket to this principal.
        if error.response.get("Error", {}).get("Code") not in {
            "BucketAlreadyOwnedByYou",
            "BucketAlreadyExists",
        }:
            print(f"FATAL: cannot create bucket {bucket}: {error}", file=sys.stderr)
            raise SystemExit(1)
        print(f"bucket {bucket} already exists")
PY
fi

# --- Account schema ----------------------------------------------------------
# Not run at boot in the general case (see scripts/migrate-auth.mjs), but a
# single-container deployment has no separate release step to hang it on, and
# an unmigrated database means sign-in fails with a SQL error.
(cd /app/frontend && node scripts/migrate-auth.mjs)

# --- Both processes ----------------------------------------------------------
# If either dies the container should die, so an orchestrator restarts it
# rather than serving a front end with no backend behind it.
terminate() {
  kill -TERM "${backend_pid:-}" "${frontend_pid:-}" 2>/dev/null || true
  wait
}
trap terminate TERM INT

python -m uvicorn pydexpi_datalog.web.asgi:app --host 0.0.0.0 --port 8000 &
backend_pid=$!

(cd /app/frontend && exec node_modules/.bin/next start --hostname 0.0.0.0 --port 3000) &
frontend_pid=$!

echo "pydexpi-datalog is up: ${BETTER_AUTH_URL}"

wait -n "${backend_pid}" "${frontend_pid}"
echo "a process exited; shutting the container down" >&2
terminate
exit 1
