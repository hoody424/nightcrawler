#!/bin/sh
# Started as root (the default): give the crawler user the requested PUID/PGID
# (Unraid: 99/100), make /data its own and drop privileges. Started with
# --user, nightcrawler runs as that user directly.
set -e

if [ "$(id -u)" = 0 ]; then
    PUID=${PUID:-10001}
    PGID=${PGID:-10001}
    [ "$(id -g crawler)" = "$PGID" ] || groupmod -o -g "$PGID" crawler
    [ "$(id -u crawler)" = "$PUID" ] || usermod -o -u "$PUID" crawler
    mkdir -p /data/claude
    # Only touch what is wrong, so a big volume does not slow down every start.
    find /data /home/crawler \( ! -user "$PUID" -o ! -group "$PGID" \) -exec chown -h "$PUID:$PGID" {} +
    export HOME=/home/crawler
    exec setpriv --reuid=crawler --regid=crawler --init-groups python -m nightcrawler "$@"
fi

exec python -m nightcrawler "$@"
