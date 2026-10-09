#!/bin/sh
# Start aimm as the unprivileged `aimm` user.
#
# Started as root (the default), this
#   - gives the `aimm` user the PUID/PGID you ask for (default 1000:1000), so that files in the
#     data folder belong to your user on the host,
#   - makes the data folder (/data) writable by that user,
#   - keeps a data folder mounted at the old location, /root/.ai-marketplace-monitor, working,
# and then runs supervisord as `aimm`. Started as another user (`docker run --user`, `user:` in
# Compose), it runs supervisord as that user, and the data folder must be writable by it.
set -eu

DATA=/data
LEGACY=/root/.ai-marketplace-monitor

if [ "$(id -u)" = 0 ]; then
    PUID=${PUID:-1000}
    PGID=${PGID:-1000}
    if [ "$(id -g aimm)" != "$PGID" ]; then
        groupmod -o -g "$PGID" aimm
    fi
    if [ "$(id -u aimm)" != "$PUID" ]; then
        usermod -o -u "$PUID" aimm
    fi
    chown aimm:aimm /home/aimm

    # images up to 0.10.10 kept the data in /root/.ai-marketplace-monitor; use a folder still
    # mounted there unless /data is mounted too
    if [ -d "$LEGACY" ] && ! mountpoint -q "$DATA"; then
        echo "aimm: using the data folder mounted at $LEGACY." \
            "Mount it at $DATA instead; the old location will stop working in a future release."
        chmod 755 /root
        rmdir "$DATA" 2>/dev/null || rm -f "$DATA"
        ln -s "$LEGACY" "$DATA"
    fi

    # only when needed: a large data folder on a NAS takes a while to walk
    if [ "$(stat -c %u:%g "$DATA/")" != "$PUID:$PGID" ]; then
        echo "aimm: giving the data folder to user $PUID:$PGID"
        chown -R "$PUID:$PGID" "$DATA/" || echo "aimm: could not change the owner of $DATA" >&2
    fi
    # supervisord sends aimm's output to the container log by opening /dev/fd/1 and /dev/fd/2
    chown aimm:aimm "/proc/$$/fd/1" "/proc/$$/fd/2" || true
    exec setpriv --reuid=aimm --regid=aimm --init-groups env HOME=/home/aimm "$@"
fi

if [ ! -w "$DATA/" ]; then
    echo "aimm: user $(id -u):$(id -g) cannot write the data folder $DATA." \
        "Give it to this user on the host (chown -R $(id -u):$(id -g) <folder>)," \
        "or start the container as root and set PUID and PGID." >&2
    exit 1
fi
if [ ! -w "$HOME" ]; then
    export HOME=/tmp/aimm-home
    mkdir -p "$HOME"
fi
exec "$@"
