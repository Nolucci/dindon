#!/usr/bin/env bash
# Check a Debian Docker installation of Dindon without printing secrets.
set -euo pipefail

PROJECT_DIR="${1:-/opt/dindon}"
if [[ ! -f "$PROJECT_DIR/docker-compose.yml" || ! -f "$PROJECT_DIR/.env" ]]; then
  echo "Installation introuvable dans $PROJECT_DIR (docker-compose.yml ou .env absent)." >&2
  exit 1
fi
cd "$PROJECT_DIR"

docker info >/dev/null
docker compose config --quiet

check_service() {
  local service="$1" container state
  container="$(docker compose --profile ollama --profile bot ps -a -q "$service")"
  if [[ -z "$container" ]]; then
    echo "ÉCHEC : service $service absent" >&2
    return 1
  fi
  state="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container")"
  if [[ "$state" != healthy && "$state" != running ]]; then
    echo "ÉCHEC : service $service : $state" >&2
    return 1
  fi
  echo "OK : service $service : $state"
}

check_service db
check_service app

ollama_container="$(docker compose --profile ollama ps -a -q ollama)"
if [[ -n "$ollama_container" ]]; then
  check_service ollama
fi

bot_container="$(docker compose --profile bot ps -a -q bot)"
if [[ -n "$bot_container" ]]; then
  check_service bot
fi

port="$(sed -n 's/^DINDON_PORT=//p' .env | tail -n 1)"
port="${port:-8000}"
if [[ ! "$port" =~ ^[0-9]+$ ]]; then
  echo "ÉCHEC : DINDON_PORT doit être un numéro de port." >&2
  exit 1
fi

health="$(curl --fail --silent --show-error --max-time 10 "http://127.0.0.1:$port/health")"
embed_model="$(sed -n 's/^DINDON_EMBED_MODEL=//p' .env | tail -n 1)"
naming_model="$(sed -n 's/^DINDON_NAMING_MODEL=//p' .env | tail -n 1)"
printf '%s\n' "$health" | python3 -c '
import json, sys
data = json.load(sys.stdin)
database = data.get("database", {})
ollama = data.get("ollama", {})
models = ollama.get("models", [])
needed = (sys.argv[1], sys.argv[2])
missing = [name for name in needed if name not in models and name + ":latest" not in models]
if data.get("status") != "ok" or database.get("tables", 0) == 0:
    sys.exit("ÉCHEC : la réponse /health ne confirme pas la base de données")
tables = database["tables"]
migrations = database.get("migrations_applied", 0)
print(f"OK : HTTP /health, {tables} tables, {migrations} migrations")
if not ollama.get("reachable") or missing:
    sys.exit("ÉCHEC : Ollama ou modèles manquants : " + ", ".join(missing))
print("OK : Ollama et modèles " + ", ".join(needed))
' "${embed_model:-bge-m3}" "${naming_model:-qwen3:14b}"

html="$(curl --fail --silent --show-error --max-time 10 "http://127.0.0.1:$port/")"
if [[ "$html" != *'<html'* ]]; then
  echo "ÉCHEC : la page de connexion ne répond pas." >&2
  exit 1
fi
echo "OK : interface sur http://127.0.0.1:$port"

docker compose exec -T app dindon check >/dev/null
echo "OK : contrôle de la base par Dindon"
if [[ -n "$bot_container" ]]; then
  docker compose exec -T bot dindon preflight
  echo "OK : configuration Discord et permissions du bot"
fi
echo "Dindon est lancé. L’accès est local au serveur ; utilisez un tunnel SSH pour ouvrir l’interface depuis votre poste."
