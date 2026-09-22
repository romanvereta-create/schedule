# Security launch gates

## P0 — must close before public production

- **Encrypt backups at rest.** Current storage archives and candidate replicas
  are ordinary ZIP files containing personal and financial records. Introduce
  authenticated encryption with a key held outside both storage locations,
  define key rotation/recovery, and complete an encrypted restore drill.
- **Approve data roles and retention.** Encryption does not replace deletion,
  minimization, processor contracts, or legal retention rules.

## P1 — must close before untrusted/public users

- Separate storage credentials into application read/write, backup-reader, and
  restore-administrator scopes. Rotate the legacy all-powerful token after migration.
- Require a strong, short-lived restore authorization separate from ordinary API access.
- Apply API request/body limits and per-user/IP rate limits, with stricter limits
  for writes, exports, uploads, and PDF generation.
- Reduce Telegram `initData` reuse from 24 hours to a short configurable window
  and move mutating calls toward a short-lived server session/nonce.
- If TEMLI is not open self-service, require an explicit invitation/entitlement
  before creating a teacher tenant.
- Decode, verify, pixel-limit, and safely re-encode every uploaded image.

## P2 — defense in depth

- Add a strict Content Security Policy and Permissions Policy compatible with Telegram.
- Return generic errors with correlation IDs; keep paths and exception text out of responses.
- Run the container as a non-root user and keep writable paths minimal.
- Protect detailed readiness metadata or expose a separate minimal public liveness endpoint.
- Produce an SBOM and run dependency/image vulnerability scans for each release.

## Existing positive controls

- production fails closed when unauthenticated mode is enabled;
- Telegram signatures use constant-time HMAC comparison;
- CORS is bound to the configured WebApp origin;
- tenant paths are derived server-side from the signed Telegram identity;
- storage request bodies are capped;
- backup ZIP paths, size, hash, and manifest are validated;
- restore creates a safety backup;
- candidate replicas verify archive hashes/manifests;
- releases expose a non-secret public identifier and have preflight checks.
