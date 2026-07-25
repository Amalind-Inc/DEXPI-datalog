# The hosted profile in one image: Next front end, FastAPI backend, Souffle.
#
# Both processes ship together on purpose. They are one deployment unit -- the
# front end proxies every review call to the backend and neither is useful
# alone -- and a single container is what makes `docker compose up` a true
# quickstart rather than an orchestration exercise.
#
# linux/amd64 only. Souffle publishes no arm64 release, and building it from
# source would turn a two-minute image into a twenty-minute one. On Apple
# Silicon this runs under emulation: slower, but the same binary CI tests.

# ---- Frontend build ---------------------------------------------------------
FROM node:22-bookworm-slim AS frontend

WORKDIR /app/frontend

# Dependencies first, so a source-only edit does not reinstall node_modules.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./

# The build inlines NEXT_PUBLIC_* only; every value this app reads is a server
# variable resolved at runtime, so one image serves any deployment.
RUN npm run build

# Ubuntu 24.04, not Debian, and that is forced rather than chosen: Souffle
# publishes one Linux binary, built for noble, needing libc6 >= 2.38 and
# libstdc++6 >= 13.1. Bookworm ships 2.36 and 12.2, so the .deb refuses to
# install there. Matching CI's runner is also what makes the pinned checksum
# below mean the same thing here as it does in the workflow.
FROM ubuntu:24.04 AS runtime

# Souffle, pinned to the same release and checksum as .github/workflows/ci.yml.
# Keep the three values in step: an image running a different Souffle than CI
# tested would make green CI a claim about a binary nobody ships.
ARG SOUFFLE_VERSION=2.5
ARG SOUFFLE_SHA512=6b86e554f6aa5abf8a8b55d8312ae37c0957c5bd6c9edeea89246db9406f645ec5e600b84fe6636b1c163da556f0da6c3d2dad46c1083413f2fcf4f95b9ac62c

ENV DEBIAN_FRONTEND=noninteractive

RUN set -eux; \
    apt-get update; \
    apt-get install --yes --no-install-recommends \
        ca-certificates curl openssl \
        python3 python3-venv libpython3-stdlib; \
    # Node, to run the built front end.
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -; \
    apt-get install --yes --no-install-recommends nodejs; \
    # Souffle, verified before it is trusted.
    deb="x86_64-ubuntu-2404-souffle-${SOUFFLE_VERSION}-Linux.deb"; \
    curl --fail --location --silent --show-error --output "/tmp/${deb}" \
        "https://github.com/souffle-lang/souffle/releases/download/${SOUFFLE_VERSION}/${deb}"; \
    echo "${SOUFFLE_SHA512}  /tmp/${deb}" | sha512sum --check --strict; \
    apt-get install --yes "/tmp/${deb}"; \
    rm -f "/tmp/${deb}"; \
    apt-get autoremove --yes; \
    rm -rf /var/lib/apt/lists/*; \
    souffle --version; \
    python3 --version

# A virtualenv rather than --break-system-packages: Ubuntu marks its Python
# externally managed (PEP 668), and overriding that to install into the system
# interpreter is how an apt upgrade later removes your dependencies.
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv "${VIRTUAL_ENV}"
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

WORKDIR /app

# Python dependencies before source, for the same layer-caching reason.
#
# pyDEXPI is a git submodule and an editable install, not a PyPI package, so a
# clone without `--recurse-submodules` produces an empty directory and a build
# that fails here rather than at runtime.
COPY pyDEXPI/ ./pyDEXPI/
RUN pip install --no-cache-dir -e ./pyDEXPI

COPY pyproject.toml README.md ./
COPY pydexpi_datalog/__init__.py ./pydexpi_datalog/
RUN pip install --no-cache-dir -e ".[hosted]"

COPY pydexpi_datalog/ ./pydexpi_datalog/
COPY TrainingTestCases/ ./TrainingTestCases/

# The built front end, its runtime dependencies, and the auth migration script.
COPY --from=frontend /app/frontend/.next ./frontend/.next
COPY --from=frontend /app/frontend/node_modules ./frontend/node_modules
# No `public/`: this app ships no static files outside the build output.
COPY frontend/package.json frontend/next.config.ts ./frontend/
COPY frontend/lib ./frontend/lib
COPY frontend/scripts ./frontend/scripts

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Accounts and generated secrets live here. Mount a volume on it or a redeploy
# takes every account with it -- the entrypoint refuses to start if it is not
# writable rather than letting that happen quietly.
ENV PYDEXPI_STATE_DIR=/data
VOLUME ["/data"]

ENV PYDEXPI_DEPLOYMENT_PROFILE=hosted \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    NODE_ENV=production

EXPOSE 3000 8000

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
