#!/usr/bin/env bash
# The AI stages on the political test server (database dindon_politique), then the comparison with its ground truth.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
export DATABASE_URL="postgresql://dindon:${POSTGRES_PASSWORD}@127.0.0.1:${POSTGRES_PORT:-5432}/dindon_politique" OLLAMA_URL=http://127.0.0.1:11434
.venv/bin/dindon analyze
.venv/bin/dindon analyze --stage claims --limit "${LIMIT:-150}"      # reading the positions is long (about 15 s per conversation)
.venv/bin/python tools/evaluate_political.py --report political/RAPPORT-THEMES.txt --judge --positions-report political/RAPPORT-POSITIONS.txt --coherence-report political/RAPPORT-ROLES.txt
