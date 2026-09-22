# TEMLI incident runbook

## Severity

- **SEV-1:** unauthorized access, suspected token/key exposure, data corruption,
  loss of all current storage, or messages/payments attributed to the wrong tenant.
- **SEV-2:** candidate unavailable, storage unavailable, stale/unverified backups,
  broken authentication, or repeatable payment/accounting inconsistency.
- **SEV-3:** degraded performance or an isolated feature failure with a safe workaround.

## First response

1. Record UTC and Moscow time, affected environment, public release ID, and
   the reporter's description. Do not copy personal data into the incident log.
2. Check the candidate `/api/health`, candidate `/api/ready`, and storage
   `/health` endpoints.
3. For a suspected confidentiality or tenant-isolation incident, stop only the
   candidate. Do not touch legacy production or delete any data.
4. Preserve logs and backup metadata. Never paste tokens or response bodies
   containing user data into tickets or chats.
5. Assign an incident owner and a communications owner.

## Safe containment

- A leaked Telegram or storage credential is rotated at its issuing system;
  editing source code is not a credential rotation.
- A bad candidate release is rolled back by reverting the offending commit in
  `schedule-production-candidate`, pushing the revert to `main`, then using
  BotHost “Update from Git”. Avoid force-pushes and destructive Git resets.
- Storage restore is never the first reaction to an application bug. Stop
  writes, take a fresh safety backup, verify the selected archive, and restore
  only after the incident owner approves the exact target.

## Recovery verification

- Run the public post-deploy checker.
- Confirm the release ID changed to the intended version.
- Confirm the source backup and offsite replica are current and verified.
- Exercise one read-only Telegram session before allowing writes.
- For a data incident, compare aggregate counts only and inspect payment
  transaction recovery state before reopening writes.

## Closure

Document cause, affected time range, affected data categories, recovery steps,
and preventive action. A personal-data incident also enters the legal response
process; the technical team must not decide notification duties on its own.
