#!/bin/sh
# `docker exec` runs as root. Run the CLI as the crawler user so a login it
# writes to /data/claude stays readable for nightcrawler.
if [ "$(id -u)" = 0 ]; then
    export HOME=/home/crawler
    exec setpriv --reuid=crawler --regid=crawler --init-groups /opt/claude-code/bin/claude.exe "$@"
fi
exec /opt/claude-code/bin/claude.exe "$@"
