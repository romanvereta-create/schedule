# Backup and restore drill

The purpose is to prove recoverability without writing to live storage.

## Frequency

- Automated backup and integrity status: continuously, exposed through readiness.
- Operator review of backup age and replica age: at every release.
- Isolated restore drill: monthly and before production promotion.

## Preconditions

- Keep `TEMLI_BACKUP_ENCRYPTION_KEY` only in the storage service secret store.
  It must be URL-safe base64 for exactly 32 random bytes and must not be copied
  into Git, an archive, a replica directory, or a drill report.
- Use the newest archive reported as verified by Russian storage.
- Record its name, SHA-256, creation time, and release ID without recording data content.
- Restore only into a new temporary directory or isolated test service.
- Never point a drill at the live `DATA_DIR` or `/app/data` tree.

## Drill

1. Download the selected encrypted archive through the authenticated backup endpoint.
2. Verify the outer SHA-256, decrypt/authenticate it in the isolated drill
   process, and verify every member declared by `manifest.json`.
3. Reject duplicate paths, traversal paths, unexpected members, invalid JSON,
   and archives above the configured compressed/uncompressed limits.
4. Restore into an empty temporary directory.
5. Run structural validation and collect aggregate teacher, student, lesson,
   workbook, personal-bot, and pending-transaction counts.
6. Verify required encrypted records can be decrypted using the production key
   without printing decrypted values.
7. Confirm the source archive hash did not change and destroy the temporary
   restored copy after recording the result.

## Pass criteria

- archive and manifest integrity pass;
- all required JSON documents parse and required files exist;
- no pending payment-recovery transaction remains unexplained;
- aggregate counts are plausible compared with the prior drill;
- the live source is unchanged;
- no personal data appears in logs or the drill report.

## Failure

Treat failure as SEV-2. Keep live storage untouched, retain the failed archive
and generic error type, select the preceding verified archive, and investigate
before the next release.

## One-time plaintext migration

Existing ZIP backups are never accepted implicitly once encryption is enabled.
For the migration restart only, set both
`TEMLI_ALLOW_PLAINTEXT_BACKUPS=true` and
`TEMLI_MIGRATE_PLAINTEXT_BACKUPS=true`. The service validates each legacy ZIP,
atomically replaces it with an authenticated encrypted envelope, and verifies
the result. Confirm readiness and an isolated restore, then remove both flags
(or set them to `false`) and restart. New backups are always encrypted whenever
`TEMLI_BACKUP_ENCRYPTION_KEY` is configured.

Keep an escrowed copy of the encryption key outside the storage host. Losing
the key makes every encrypted backup and off-site replica unrecoverable.
