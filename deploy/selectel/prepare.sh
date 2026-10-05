#!/bin/sh
set -eu

cd "$(dirname "$0")"

for file in .env app.env shared.env storage.env; do
    if [ ! -s "$file" ]; then
        echo "Missing deploy/selectel/$file" >&2
        exit 1
    fi
done

chmod 600 app.env shared.env storage.env
docker compose config --quiet
docker compose build app storage
docker compose pull caddy
docker compose up -d storage caddy

echo "Storage and HTTPS gateway started. Telegram polling is still stopped."
