# Selectel deployment

This deployment keeps application data on one Russian Selectel VPS. Only the
Telegram Bot API transport uses `TELEGRAM_PROXY_URL`; no global proxy variables
are configured.

Public ports: `80/tcp`, `443/tcp`, and `443/udp`. The application and storage
ports are private Docker-network endpoints. The storage network is marked
`internal`, so the storage container has no outbound internet route.

Live records and encrypted backup archives use separate host directories,
`/var/lib/temli/storage` and `/var/lib/temli/backups`, to preserve the storage
service's restore and corruption-safety boundary.

## Files containing secrets

- `app.env`: central bot token, owner id, Telegram-only proxy, application keys.
- `shared.env`: scoped application and backup-read storage tokens.
- `storage.env`: storage admin token and backup encryption key.

These files are ignored by Git and must have mode `0600`.

## Safe launch order

1. Run `prepare.sh`. It starts storage and Caddy only.
2. Verify the HTTPS endpoint and migrate/verify existing test data.
3. Stop the old BotHost polling process.
4. Run `OLD_BOT_STOPPED=yes ./cutover.sh`.

Never run the final step while the same bot token is polling on BotHost.

`init-secrets.py` consumes a temporary `migration.env`, generates independent
application/storage keys with the operating-system CSPRNG, writes each secret
file as mode `0600`, and removes the temporary file from the server.
