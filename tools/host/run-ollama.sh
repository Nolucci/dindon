#!/bin/sh
# Keeps one Ollama server on 127.0.0.1:11434 for Dindon's analysis. Started at login by the LaunchAgent com.dindon.ollama
# (see install.sh). If a server is already there (the Ollama application's own, or one started by hand) it only watches, and takes
# over if that one goes away: there is never a second server fighting for the port.
LOG="$HOME/Library/Application Support/Dindon/logs/ollama.log"
mkdir -p "$(dirname "$LOG")"
while true; do
  if ! /usr/bin/curl -s -m 3 -o /dev/null http://127.0.0.1:11434/api/version; then
    echo "$(date '+%F %T') starting ollama serve" >> "$LOG"
    OLLAMA_HOST=127.0.0.1:11434 OLLAMA_KEEP_ALIVE=10m /opt/homebrew/bin/ollama serve >> "$LOG" 2>&1 &
    wait $!
    echo "$(date '+%F %T') ollama serve ended" >> "$LOG"
  fi
  sleep 15
done
