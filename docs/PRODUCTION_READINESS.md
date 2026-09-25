# TEMLI production readiness

This document is the release gate for the new production candidate. It does
not authorize changes to the legacy production bot.

## Protected environments

- Legacy production: `bot-1787954043-4984-solo1986.bothost.tech`. Never
  update, restart, or reconfigure it as part of candidate work.
- Production candidate: `bot-1790109000-5632-solo1986.bothost.tech`.
- Russian storage: `bot-1789853066-7755-solo1986.bothost.tech`.
- Bot3 test environment: `bot-1789984567-3598-solo1986.bothost.tech`.

## Automated launch gate

Run from a trusted workstation:

```text
python check_bot3_postdeploy.py \
  --bot-base-url https://bot-1790109000-5632-solo1986.bothost.tech \
  --storage-base-url https://bot-1789853066-7755-solo1986.bothost.tech
```

The release is blocked unless all checks return `status: ok`, the latest
source backup is verified and younger than eight hours, and at least one
offsite replica exists and is younger than eight hours.

The health gate also requires initialized/running Telegram polling and recent
request diagnostics. A pending long poll is normal; this snapshot is not proof
of successful message delivery. A manual `/start` reply from the candidate
with the old test poller stopped remains mandatory. These checks do not verify
data residency or legal compliance; see `RUSSIA_CANDIDATE_AUDIT.md`.

## Manual launch gate

- Open the candidate through its Telegram button, never by a bare browser URL.
- Verify calendar load, student selection, lesson opening, settings, and close/reopen.
- Perform one controlled create/edit/delete cycle using an explicitly named
  test record. Do not use a real student's identity.
- Verify payment, receipt, reversal, and accounting-book behavior only in an
  approved test tenant because candidate and Bot3 share storage.
- Confirm that the legacy production bot remains online and unchanged.
- Record the candidate release identifier returned by `/api/health`.

## Promotion gate

Promotion requires all of the following:

- seven consecutive days without a severity-1 or severity-2 incident;
- a successful isolated restore drill from the newest verified archive;
- approved privacy policy, user agreement, consent wording, and data-retention rules;
- an identified operator/contact for personal-data requests and incidents;
- a written rollback owner and a tested rollback procedure;
- no unresolved P0/P1 security findings.

## Evidence to retain

Keep only non-sensitive evidence: timestamp, public release identifier,
health-check result, backup count/age, restore-drill result, and approver. Never
copy storage tokens, Telegram tokens, student names, contacts, notes, receipts,
or archive contents into release logs.
