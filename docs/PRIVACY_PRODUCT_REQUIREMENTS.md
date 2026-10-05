# Privacy product requirements

These are implementation tasks derived from the legal draft. Exact wording and
legal grounds require approval, but engineering can proceed in parallel.

## User-visible

- Add permanent links in settings to the current privacy policy, separate
  consent, user agreement, and privacy-request channel.
- Add a separate, unbundled consent screen with document version/hash and a
  positive user action; never pre-check acceptance.
- Add “Export my data”, “Withdraw consent”, and “Delete account/request deletion”.
- Explain that payment/receipt records are informational unless TEMLI later
  integrates a regulated fiscal/payment provider.
- Add a clear warning not to enter health, diagnosis, or other sensitive data in notes.
- Add a teacher confirmation that a lawful basis/parental authorization exists
  before storing a minor's personal contact details.

## Server-side

- Persist acceptance version, SHA-256, UTC timestamp, Telegram user ID, language,
  and withdrawal status in the tenant scope.
- Implement a request state machine: received, identity checked, processing,
  completed/refused, response deadline, deletion proof.
- Export only the authenticated tenant; deletion must not cross tenant boundaries.
- Maintain a restore suppression/tombstone mechanism so data deleted from active
  storage is not silently resurrected from a rotating backup.
- Keep application and incident logs free of names, contacts, notes, receipt
  contents, Telegram initData, tokens, and archive contents.

## Release gate

Do not expose placeholder legal documents. The application may ship technical
hooks behind a disabled feature flag, but public links and consent collection
activate only after the operator identity, approved versions, and request
contact are configured.
