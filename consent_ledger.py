"""Append-only acceptance ledger for versioned legal documents."""
import datetime
import hashlib
import hmac
import json
import re

DOCUMENT_TYPES = ("user_agreement", "personal_data_consent")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")

class ConsentConfigurationError(RuntimeError):
    pass

class ConsentLedgerError(RuntimeError):
    pass

def ledger_hmac_key(environ):
    value = str(environ.get("TEMLI_CONSENT_LEDGER_HMAC_KEY", ""))
    raw = value.encode("utf-8")
    if len(raw) < 32:
        raise ConsentConfigurationError("invalid_consent_ledger_hmac_key")
    return raw

def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def document_config(environ):
    result = {}
    names = {"user_agreement": "TEMLI_USER_AGREEMENT", "personal_data_consent": "TEMLI_PERSONAL_DATA_CONSENT"}
    for kind, prefix in names.items():
        identifier = str(environ.get(prefix + "_ID", "")).strip()
        version = str(environ.get(prefix + "_VERSION", "")).strip()
        digest = str(environ.get(prefix + "_SHA256", "")).strip().lower()
        if not identifier or not version or not _SHA256_RE.fullmatch(digest):
            raise ConsentConfigurationError(f"invalid_{kind}_configuration")
        result[kind] = {"document_id": identifier, "version": version, "document_sha256": digest}
    return result

def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

def _validate_ledger(raw, integrity_key):
    if raw in (None, {}):
        return {"schema": 1, "events": []}
    if not isinstance(raw, dict) or raw.get("schema") != 1 or not isinstance(raw.get("events"), list):
        raise ConsentLedgerError("invalid_consent_ledger")
    previous = ""
    for event in raw["events"]:
        if not isinstance(event, dict):
            raise ConsentLedgerError("invalid_consent_event")
        supplied = event.get("event_sha256", "")
        unsigned = {key: value for key, value in event.items() if key != "event_sha256"}
        if unsigned.get("previous_event_sha256", "") != previous:
            raise ConsentLedgerError("broken_consent_chain")
        expected = hmac.new(integrity_key, _canonical(unsigned), hashlib.sha256).hexdigest()
        if not isinstance(supplied, str) or not hmac.compare_digest(supplied, expected):
            raise ConsentLedgerError("invalid_consent_event_digest")
        previous = supplied
    return raw

def status(raw, teacher_id, documents, integrity_key):
    ledger = _validate_ledger(raw, integrity_key)
    teacher_id = int(teacher_id)
    current = {}
    for kind in DOCUMENT_TYPES:
        document = documents[kind]
        matching = [event for event in ledger["events"] if event.get("type") == kind]
        latest = matching[-1] if matching else None
        accepted = bool(latest and latest.get("action") == "accepted"
                        and latest.get("telegram_teacher_id") == teacher_id
                        and latest.get("document_id") == document["document_id"]
                        and latest.get("version") == document["version"]
                        and latest.get("document_sha256") == document["document_sha256"])
        current[kind] = {**document, "accepted": accepted}
        if latest:
            current[kind]["last_action"] = latest.get("action")
            current[kind]["last_action_at"] = latest.get("accepted_at") or latest.get("revoked_at")
    return {"ready": all(item["accepted"] for item in current.values()), "documents": current}

def append_events(raw, teacher_id, documents, integrity_key, kinds, action, now=None):
    ledger = _validate_ledger(raw, integrity_key)
    teacher_id = int(teacher_id)
    if action not in {"accepted", "revoked"}:
        raise ValueError("invalid action")
    requested = list(dict.fromkeys(kinds))
    if not requested or any(kind not in DOCUMENT_TYPES for kind in requested):
        raise ValueError("invalid document type")
    timestamp = now or utc_now()
    previous = ledger["events"][-1]["event_sha256"] if ledger["events"] else ""
    for kind in requested:
        event = {"type": kind, "action": action, "telegram_teacher_id": teacher_id,
                 **documents[kind], "previous_event_sha256": previous}
        event["accepted_at" if action == "accepted" else "revoked_at"] = timestamp
        event["event_sha256"] = hmac.new(integrity_key, _canonical(event), hashlib.sha256).hexdigest()
        ledger["events"].append(event)
        previous = event["event_sha256"]
    return ledger
