# Consent ledger integration

TEMLI keeps public self-service registration open. A newly authenticated Telegram teacher is registered normally, but tenant APIs return HTTP `428` with `code: consent_required` until both current documents are accepted separately.

Required environment variables (deployment must fail closed if any are absent or invalid):

- `TEMLI_USER_AGREEMENT_ID`, `TEMLI_USER_AGREEMENT_VERSION`, `TEMLI_USER_AGREEMENT_SHA256`
- `TEMLI_PERSONAL_DATA_CONSENT_ID`, `TEMLI_PERSONAL_DATA_CONSENT_VERSION`, `TEMLI_PERSONAL_DATA_CONSENT_SHA256`
- `TEMLI_CONSENT_LEDGER_HMAC_KEY`: a dedicated random secret of at least 32 bytes; never reuse a storage or backup key.

Each SHA-256 value is the lowercase digest of the exact published document bytes. Changing an ID, version, or digest requires acceptance again.

Frontend contract after valid Telegram `initData`:

- `GET /api/consent/status`
- `POST /api/consent/accept` with `{"documents":["user_agreement"]}` or `{"documents":["personal_data_consent"]}`; present two independent controls and do not pre-check either one.
- `POST /api/consent/revoke` with the same shape.

Records are tenant-isolated, append-only audit events in `consent_ledger.json`. They contain the numeric Telegram teacher ID, UTC timestamp, document identity/version/digest, and a chained event digest. Raw Telegram `initData` is never stored. Revocation appends an event and immediately blocks normal tenant APIs. Health, readiness, and static frontend files remain available.

Safe activation order: deploy with `TEMLI_CONSENT_ENFORCEMENT=false` (the default), configure the documents and dedicated HMAC key, ship/test the two-checkbox frontend flow, then set `TEMLI_CONSENT_ENFORCEMENT=true` and restart. When enforcement is true, missing/invalid configuration fails closed with HTTP `503`.
