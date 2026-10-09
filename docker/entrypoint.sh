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
    # numbers other than 0, which would make the `aimm` user root
    for id in "$PUID" "$PGID"; do
        case "$id" in '' | *[!0-9]*) id=0 ;; esac
        if [ "$id" -eq 0 ]; then
            echo "aimm: PUID and PGID must be user and group IDs other than 0 (got $PUID:$PGID)." >&2
            exit 1
        fi
    done
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

    # The directory may already belong to this user while files from the old root-run
    # image do not. Inspect contents too, and only chown entries that need migration.
    # Do not follow symlinks into files outside the data directory.
    echo "aimm: checking data folder ownership for user $PUID:$PGID"
    if ! find "$DATA/" \( ! -uid "$PUID" -o ! -gid "$PGID" \) \
        -exec chown -h "$PUID:$PGID" {} +; then
        echo "aimm: cannot migrate ownership of $DATA; fix its permissions on the host." >&2
        exit 1
    fi
    # supervisord sends aimm's output to the container log by opening /dev/fd/1 and /dev/fd/2
    chown aimm:aimm "/proc/$$/fd/1" "/proc/$$/fd/2" || true
    exec setpriv --reuid=aimm --regid=aimm --init-groups env HOME=/home/aimm "$@"
fi

# without root, /data cannot be pointed at the old location
if [ -d "$LEGACY" ] && ! mountpoint -q "$DATA"; then
    echo "aimm: the data folder is mounted at $LEGACY, which works only when the container" \
        "starts as root. Mount it at $DATA instead." >&2
    exit 1
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
