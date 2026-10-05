# Production-candidate preflight

`candidate_preflight.py` is a local, fail-closed gate. It performs no network
requests and never prints environment values or secrets.

Before building a candidate, set all runtime variables plus a non-secret
candidate marker:

```text
TEMLI_DEPLOYMENT_ID=temli-production-candidate
```

The candidate must also have its own `SCHEDULE_BOT_USERNAME`, a self-hosted
`SCHEDULE_WEBAPP_URL` ending in `/app/`, the matching
`SCHEDULE_WEBAPP_ORIGIN`, and an HTTPS `TEMLI_STORAGE_URL`. The known live bot
username and live backend host are rejected.

Run the gate inside the candidate container or from its deployment shell:

```sh
python candidate_preflight.py
```

Exit code `0` and top-level `"status": "ok"` allow the candidate build to
continue. Any error blocks deployment. The command validates configuration
only; use `python check_bot3_postdeploy.py` after deployment for live health,
readiness, storage and backup checks.
