#!/bin/sh
# Installs what keeps Dindon running when nobody is at the computer: Ollama restarted at login, a nightly backup of the database.
# Nothing here needs administrator rights; `sh tools/host/install.sh --remove` takes it all away (the backups are kept).
# The scripts are copied to ~/Library/Application Support/Dindon/bin: a job started by launchd may not read ~/Desktop or ~/Documents.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
BASE="$HOME/Library/Application Support/Dindon"
AGENTS="$HOME/Library/LaunchAgents"
UID_NUM="$(id -u)"

if [ "$1" = "--remove" ]; then
  for label in com.dindon.ollama com.dindon.backup; do
    launchctl bootout "gui/$UID_NUM/$label" 2>/dev/null || true
    rm -f "$AGENTS/$label.plist"
  done
  echo "removed (the scripts in $BASE/bin and the backups are kept)"
  exit 0
fi

mkdir -p "$BASE/bin" "$BASE/logs" "$BASE/backups" "$AGENTS"
cp "$HERE/run-ollama.sh" "$HERE/backup.sh" "$BASE/bin/"
chmod 755 "$BASE/bin/run-ollama.sh" "$BASE/bin/backup.sh"

cat > "$AGENTS/com.dindon.ollama.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.dindon.ollama</string>
  <key>ProgramArguments</key><array><string>/bin/sh</string><string>$BASE/bin/run-ollama.sh</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ProcessType</key><string>Background</string>
</dict></plist>
PLIST

cat > "$AGENTS/com.dindon.backup.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.dindon.backup</string>
  <key>ProgramArguments</key><array><string>/bin/sh</string><string>$BASE/bin/backup.sh</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>3</integer><key>Minute</key><integer>30</integer></dict>
  <key>ProcessType</key><string>Background</string>
</dict></plist>
PLIST

for label in com.dindon.ollama com.dindon.backup; do
  launchctl bootout "gui/$UID_NUM/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$UID_NUM" "$AGENTS/$label.plist"
done
echo "installed: Ollama is kept up at login, the database is saved every night at 03:30 into $BASE/backups (14 days kept)"
