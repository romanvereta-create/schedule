#!/bin/sh
set -eu

cd "$(dirname "$0")"

if [ "${OLD_BOT_STOPPED:-}" != "yes" ]; then
    echo "Refusing to start Telegram polling until OLD_BOT_STOPPED=yes is set." >&2
    exit 1
fi

docker compose up -d app
docker compose ps

echo "TEMLI application started on the Selectel VPS."
