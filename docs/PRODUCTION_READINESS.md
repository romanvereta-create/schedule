# TEMLI production readiness

This document is the release gate for the Selectel deployment. It does not authorize restarting or reusing any deprecated BotHost environment.

## Current environment

- Server: Selectel VDS `temli-prod`.
- Selected location: Moscow, `ru-2c`.
- Public IP: `135.106.173.105`.
- Public application URL: `https://temli.135-106-173-105.sslip.io/app/`.
- Storage: private Docker network; no public storage port.
- Persistent directories: `/var/lib/temli/storage`, `/var/lib/temli/backups`, `/var/lib/temli/replica`.
- Telegram: Bot API only through `TELEGRAM_PROXY_URL`; all other application traffic direct.

## Automated launch gate

The release is blocked unless health/ready checks return `status: ok`, Telegram polling is running, the newest local backup is verified and recent, and restore validation succeeds.

Local `backups` and `replica` are not an offsite copy because they reside on the same VDS. Before real-user production, require a verified encrypted copy in another Russian failure domain.

## Manual launch gate

- Open the Mini App through the current Telegram bot button.
- Verify calendar load, student selection, lesson opening, settings and close/reopen.
- Create, edit and delete only an explicitly named test record.
- Verify payment, reversal, drag-and-drop and receipt behavior.
- Verify one `/start` reply and branded-bot behavior.
- Confirm that automatic student/parent messages are unavailable without a branded teacher bot.
- Record the deployed Git commit/image and the public release identifier.

## Legal launch gate

Before the first real teacher, student or parent:

- Selectel's processing instruction is signed and its applicability to VDS is confirmed;
- the Roskomnadzor operator notification is filed;
- Telegram cross-border processing is cleared or disabled for real data;
- privacy policy, terms, consents and teacher processing instruction are approved and published;
- minors workflow is approved;
- offsite Russian backup and restore are tested;
- internal ISPDn acts and incident procedures are signed.

See `legal/COMPLIANCE_STATUS_2026-09-25.md`, `legal/SELECTEL_152_EVIDENCE.md`, and `legal/INTERNATIONAL_SALES_READINESS.md`.

## Evidence to retain

Keep only non-sensitive evidence: timestamp, release identifier, health result, backup age/count, restore result and approver. Never copy tokens, student names, contacts, notes, receipts, archive contents or proxy credentials into release logs.
