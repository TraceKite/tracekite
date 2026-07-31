#!/usr/bin/env bash
# Generate a working .env so `docker compose up` succeeds on a fresh clone.
#
# Two values have no safe default and compose refuses to boot without them:
# NEO4J_PASSWORD (the database rejects a known-default password) and
# GRAPH_HMAC_KEY (config-value redaction fails closed without a key). Both are
# generated here rather than left as an exercise, because "copy the example and
# invent two secrets" is the step where a first-time user gives up.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -f .env ]; then
  echo ".env already exists — leaving it alone."
  echo "Delete it first if you want a fresh one."
  exit 0
fi

if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl not found; cannot generate secrets." >&2
  echo "Copy .env.example to .env and fill in NEO4J_PASSWORD and GRAPH_HMAC_KEY by hand." >&2
  exit 1
fi

cp .env.example .env

# `openssl rand -hex` gives us URL/YAML-safe values, so nothing downstream has
# to worry about quoting them.
NEO4J_PASSWORD="$(openssl rand -hex 24)"
GRAPH_HMAC_KEY="$(openssl rand -hex 32)"

# BSD sed (macOS) and GNU sed disagree about -i, so write through a temp file.
tmp="$(mktemp)"
sed -e "s|^NEO4J_PASSWORD=.*|NEO4J_PASSWORD=${NEO4J_PASSWORD}|" \
    -e "s|^GRAPH_HMAC_KEY=.*|GRAPH_HMAC_KEY=${GRAPH_HMAC_KEY}|" \
    .env >"$tmp"
mv "$tmp" .env
chmod 600 .env

echo "Wrote .env with freshly generated secrets (mode 600)."
echo
echo "Next:"
echo "  docker compose up -d --build"
echo "  open http://localhost:\${FRONTEND_PORT:-28080}"
