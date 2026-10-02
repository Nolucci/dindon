#!/usr/bin/env bash
# A complete demo, without Discord, a token or any real data: an invented server answers like Discord, the first
# import is done with `dindon backfill`, then the application runs and the invented people keep talking.
# Open http://127.0.0.1:8011 (password: demo). Ctrl-C stops everything. Needs: docker, `make setup`, `make web`.
set -euo pipefail
cd "$(dirname "$0")/.."
BIN=.venv/bin
[ -x "$BIN/dindon" ] || { echo "Run 'make setup' first."; exit 1; }
[ -d web/dist ] || { echo "Run 'make web' first."; exit 1; }
set -a; [ -f .env ] && . ./.env; set +a
: "${POSTGRES_PASSWORD:?Choose a password in .env}"
docker compose up -d --wait db

DEMO=$(mktemp -d)
FAKE_PORT=8765
export DATABASE_URL="postgresql://dindon:${POSTGRES_PASSWORD}@127.0.0.1:${POSTGRES_PORT:-5432}/dindon_demo"
docker compose exec -T db psql -U dindon -d dindon -qc 'DROP DATABASE IF EXISTS dindon_demo' -c 'CREATE DATABASE dindon_demo' 2>&1 | grep -v NOTICE || true
export DINDON_PASSWORD=demo DINDON_PORT=8011 DINDON_WEB_DIR="$PWD/web/dist"
export DINDON_INBOX="$DEMO/inbox" DINDON_ARCHIVE="$DEMO/archive" DINDON_POLL_SECONDS=2
export DISCORD_TOKEN=fake-token DINDON_DISCORD_API="http://127.0.0.1:$FAKE_PORT/api/v10" FAKE_DISCORD_URL="http://127.0.0.1:$FAKE_PORT"
export DINDON_EXPORTER="$PWD/$BIN/python $PWD/tools/fake_exporter.py"
export DINDON_GUILD_IDS=$($BIN/python -c "import sys; sys.path.insert(0, 'tools'); from make_demo_server import World; print(World(seed=3, people=60).guild_id)")

cleanup() { kill $(jobs -p) 2>/dev/null || true; rm -rf "$DEMO"; }
trap cleanup EXIT INT TERM
$BIN/python tools/fake_discord.py --port $FAKE_PORT --people 60 --messages 6000 --talk > "$DEMO/fake.log" 2>&1 &
sleep 3
$BIN/dindon migrate
$BIN/dindon backfill --parallel 3
echo; echo "Open http://127.0.0.1:8011  (password: demo)   Ctrl-C to stop"
$BIN/dindon serve
