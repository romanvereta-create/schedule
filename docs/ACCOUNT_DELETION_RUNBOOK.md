# Account deletion request runbook

TEMLI records a request only after the signed-in tutor types `DELETE TEMLI`. The response contains a reference beginning with `DEL-`.

## Operator procedure

1. Locate the reference in `account_deletion_requests.json` in the configured primary storage.
2. Verify the requester through the Telegram account that owns the TEMLI workspace. Never ask for a bot token.
3. Offer the tutor a final account export and record whether it was downloaded or declined.
4. Disconnect the tutor’s branded bot and remove its encrypted credential and webhook.
5. Remove or de-identify the tutor’s live tenant files: schedule, students, settings, payments, receipts, receipt assets, workbook, invitation bindings, and consent ledger, except records that must legally be retained.
6. Remove the tutor from the tenant registry and deny new access unless they create a new account.
7. Mark the deletion request complete with completion time, operator, scope, retained categories, legal reason, and expected backup-expiry date.
8. Confirm completion to the requester without including other users’ data or internal infrastructure details.

## Important limitation

The current in-app button creates a verified pending request; it does not claim that all live data and backups disappear immediately. Before a paid launch, automate the live-data purge, add an operator queue, document the backup retention period, and test restoration to ensure deleted records expire as promised.
