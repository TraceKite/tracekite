#!/bin/bash
# Provision and run a localhost-only Neo4j 5.26 LTS for development.
# Idempotent: downloads the tarball on first run, then just starts the server.
# Requires: java 21 on PATH, NEO4J_PASSWORD in the environment (non-default).
set -euo pipefail

NEO4J_VERSION="${NEO4J_VERSION:-5.26.12}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NEO4J_HOME="$ROOT/.neo4j/neo4j"

if [ -z "${NEO4J_PASSWORD:-}" ] || [ "$NEO4J_PASSWORD" = "password" ] || [ "$NEO4J_PASSWORD" = "neo4j" ]; then
  echo "NEO4J_PASSWORD must be set to a non-default value" >&2
  exit 1
fi

if [ ! -x "$NEO4J_HOME/bin/neo4j" ]; then
  mkdir -p "$ROOT/.neo4j"
  echo "Downloading neo4j-community-$NEO4J_VERSION ..."
  curl -sfL "https://dist.neo4j.org/neo4j-community-$NEO4J_VERSION-unix.tar.gz" \
    -o "$ROOT/.neo4j/neo4j.tar.gz"
  tar xzf "$ROOT/.neo4j/neo4j.tar.gz" -C "$ROOT/.neo4j"
  rm "$ROOT/.neo4j/neo4j.tar.gz"
  mv "$ROOT/.neo4j/neo4j-community-$NEO4J_VERSION" "$NEO4J_HOME"
fi

CONF="$NEO4J_HOME/conf/neo4j.conf"
if ! grep -q "managed by repo setup" "$CONF"; then
  cat >> "$CONF" <<'EOF'

# --- managed by repo setup (localhost-only dev instance) ---
server.default_listen_address=127.0.0.1
server.memory.heap.initial_size=512m
server.memory.heap.max_size=1g
server.memory.pagecache.size=512m
db.transaction.timeout=60s
EOF
fi

if [ ! -d "$NEO4J_HOME/data/databases/neo4j" ]; then
  "$NEO4J_HOME/bin/neo4j-admin" dbms set-initial-password "$NEO4J_PASSWORD"
fi

exec "$NEO4J_HOME/bin/neo4j" console
