#!/usr/bin/env bash
# The invented POLITICAL test server (tools/make_political_server.py), in its own database, with the interface on http://127.0.0.1:8012
# (password: test). No Discord, no token: the exports are imported, then the application runs. The real data is never touched.
#   tools/politique.sh            import (again) and serve;  KEEP=1 tools/politique.sh  serves what is already there (the analysis done)
#   .venv/bin/python tools/make_political_server.py build     # first: makes political/exports and political/truth.json
set -euo pipefail
cd "$(dirname "$0")/.."
BIN=.venv/bin
[ -d political/exports ] || { echo "Run: $BIN/python tools/make_political_server.py build"; exit 1; }
[ -d web/dist ] || { echo "Run 'make web' first."; exit 1; }
set -a; [ -f .env ] && . ./.env; set +a
: "${POSTGRES_PASSWORD:?Choose a password in .env}"
docker compose up -d --wait db
# KEEP=1: serve what is there (the analysis already done) instead of starting again from the exports
if [ "${KEEP:-}" != 1 ]; then
  docker compose exec -T db psql -U dindon -d dindon -qc 'DROP DATABASE IF EXISTS dindon_politique WITH (FORCE)' -c 'CREATE DATABASE dindon_politique' 2>&1 | grep -v NOTICE || true
fi
export DATABASE_URL="postgresql://dindon:${POSTGRES_PASSWORD}@127.0.0.1:${POSTGRES_PORT:-5432}/dindon_politique"
export DINDON_PASSWORD=test DINDON_PORT=8012 DINDON_WEB_DIR="$PWD/web/dist" DINDON_COLLECTOR=off DISCORD_TOKEN= DINDON_GUILD_IDS=
export OLLAMA_URL=http://127.0.0.1:11434 DINDON_INBOX="$PWD/political/inbox" DINDON_ARCHIVE="$PWD/political/archive"
mkdir -p "$DINDON_INBOX" "$DINDON_ARCHIVE"
$BIN/dindon migrate
[ "${KEEP:-}" = 1 ] || $BIN/dindon ingest political/exports
echo; echo "Open http://127.0.0.1:8012  (password: test)   Ctrl-C to stop"
echo "The AI on this server: the page Thèmes, or  tools/politique-analyse.sh"
exec $BIN/dindon serve
