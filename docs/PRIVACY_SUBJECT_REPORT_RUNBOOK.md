# Privacy subject report runbook

`privacy_subject_report.py` is an offline, read-only discovery tool for a verified
data-subject request. It never edits storage and never prints names, contacts,
tokens, notes, record bodies, or the supplied identifier.

## Run

Use a private, operator-generated HMAC key of at least 32 bytes. Keep it out
of shell history and do not reuse an application or encryption key.

```powershell
$env:TEMLI_DSR_HASH_KEY = Read-Host -MaskInput "Temporary DSR report key"
python .\privacy_subject_report.py --storage-root 'D:\TEMLI-data' --telegram-id 123456789
Remove-Item Env:\TEMLI_DSR_HASH_KEY
```

For a teacher/account request, replace the final option with `--teacher-id ID`.
Redirect output only to an access-controlled case directory if a saved copy is
required. Run on a quiescent snapshot when consistency across files matters.

## Interpret and act

The report contains only relative file paths (tenant directory names are
HMAC-pseudonymised), categories, counts, and an HMAC-derived stable case
identifier. A non-zero exit status means the inventory
is incomplete; fix the reported malformed file or unsafe path and rerun.

Deletion is intentionally not automated. Review legal retention and accounting
requirements, referential integrity between students/schedules/payments, active
bindings and invitations, notification logs, generated receipts/assets, and all
backup generations. Record an approved per-file action, execute it using the
application's supported workflow, rerun this report, and preserve only the case
status and destruction evidence—not deleted content. Maintain a restoration
suppression marker until every applicable backup has expired or been rewritten.

The CLI refuses symlinks, path escapes, non-regular files, oversized JSON, and
malformed JSON. Do not bypass those checks or run it against live mutable files.
