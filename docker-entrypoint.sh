#!/bin/sh
# Starts the application as an ordinary user, not as root. It starts as root only to make the folders of /data (the inbox and the archive, mounted from the host)
# writable by that user, then gives up its privileges for good. If that cannot be done (an image without `setpriv`), it says so and keeps going as it is.
set -e
if [ "$(id -u)" = "0" ] && command -v setpriv >/dev/null 2>&1; then
  chown -R dindon:dindon /data 2>/dev/null || echo "docker-entrypoint: /data is not owned by the application user and cannot be changed (the host decides)" >&2
  exec setpriv --reuid=dindon --regid=dindon --init-groups "$@"
fi
exec "$@"
