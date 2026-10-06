#!/bin/sh
# A compressed dump of Dindon's database, every night (LaunchAgent com.dindon.backup, see install.sh), kept for 14 days.
# The dump holds ALL the messages: it is as private as the database itself, and stays on this machine.
DIR="$HOME/Library/Application Support/Dindon/backups"
LOG="$HOME/Library/Application Support/Dindon/logs/backup.log"
DOCKER=/usr/local/bin/docker
[ -x "$DOCKER" ] || DOCKER=/opt/homebrew/bin/docker
[ -x "$DOCKER" ] || DOCKER=/Applications/Docker.app/Contents/Resources/bin/docker
mkdir -p "$DIR" "$(dirname "$LOG")"
chmod 700 "$DIR"
NAME="$DIR/dindon-$(date +%F-%H%M).sql.gz"
if ! "$DOCKER" exec dindon-db-1 pg_isready -U dindon -q 2>/dev/null; then
  echo "$(date '+%F %T') the database is not reachable (is Docker running?): no backup" >> "$LOG"
  exit 0
fi
if "$DOCKER" exec dindon-db-1 pg_dump -U dindon dindon | gzip > "$NAME.part" && [ -s "$NAME.part" ]; then
  mv "$NAME.part" "$NAME"
  chmod 600 "$NAME"
  echo "$(date '+%F %T') ok $(basename "$NAME") $(du -h "$NAME" | cut -f1)" >> "$LOG"
else
  rm -f "$NAME.part"
  echo "$(date '+%F %T') FAILED" >> "$LOG"
  exit 1
fi
# keep the last 14
ls -1t "$DIR"/dindon-*.sql.gz 2>/dev/null | tail -n +15 | while read -r old; do rm -f "$old"; done
