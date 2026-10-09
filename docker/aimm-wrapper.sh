#!/bin/sh
# `aimm` and `ai-marketplace-monitor` in the image. `docker exec` runs commands as root; run
# them as the `aimm` user instead, so that files they write to the data folder (the cache, the
# logs) stay readable and writable by the monitor.
command=/opt/aimm/bin/$(basename "$0")
if [ "$(id -u)" = 0 ]; then
    exec setpriv --reuid=aimm --regid=aimm --init-groups env HOME=/home/aimm "$command" "$@"
fi
exec "$command" "$@"
