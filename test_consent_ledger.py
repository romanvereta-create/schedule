import json
import os
import tempfile
import unittest
from unittest.mock import patch

import bot
from consent_ledger import ConsentConfigurationError, ConsentLedgerError, append_events, document_config, ledger_hmac_key, status


DOC_ENV = {
    "TEMLI_USER_AGREEMENT_ID": "offer",
    "TEMLI_USER_AGREEMENT_VERSION": "2026-09-23",
    "TEMLI_USER_AGREEMENT_SHA256": "a" * 64,
    "TEMLI_PERSONAL_DATA_CONSENT_ID": "pd-consent",
    "TEMLI_PERSONAL_DATA_CONSENT_VERSION": "2026-09-23",
    "TEMLI_PERSONAL_DATA_CONSENT_SHA256": "b" * 64,
    "TEMLI_CONSENT_LEDGER_HMAC_KEY": "consent-only-key-32-bytes-minimum-123",
}


class ConsentLedgerUnitTests(unittest.TestCase):
    def test_requires_complete_versioned_configuration(self):
        with self.assertRaises(ConsentConfigurationError):
            document_config({})

    def test_separate_acceptance_version_change_and_revocation(self):
        documents = document_config(DOC_ENV)
        key = ledger_hmac_key(DOC_ENV)
        ledger = append_events({}, 123, documents, key, ["user_agreement"], "accepted", "2026-09-23T10:00:00Z")
        self.assertFalse(status(ledger, 123, documents, key)["ready"])
        ledger = append_events(ledger, 123, documents, key, ["personal_data_consent"], "accepted", "2026-09-23T10:01:00Z")
        self.assertTrue(status(ledger, 123, documents, key)["ready"])
        changed = json.loads(json.dumps(documents))
        changed["user_agreement"]["version"] = "2026-10-01"
        self.assertFalse(status(ledger, 123, changed, key)["ready"])
        ledger = append_events(ledger, 123, documents, key, ["personal_data_consent"], "revoked", "2026-09-23T10:02:00Z")
        self.assertFalse(status(ledger, 123, documents, key)["ready"])
        self.assertEqual(len(ledger["events"]), 3)

    def test_tampering_fails_closed(self):
        documents = document_config(DOC_ENV)
        key = ledger_hmac_key(DOC_ENV)
        ledger = append_events({}, 123, documents, key, list(documents), "accepted")
        ledger["events"][0]["version"] = "tampered"
        with self.assertRaises(ConsentLedgerError):
            status(ledger, 123, documents, key)
        fresh = append_events({}, 123, documents, key, list(documents), "accepted")
        with self.assertRaises(ConsentLedgerError):
            status(fresh, 123, documents, b"a different key that is also long enough")


class ConsentApiTests(unittest.TestCase):
    def test_api_gate_accept_and_revoke(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, DOC_ENV, clear=False), \
                patch.object(bot, "ALLOW_UNAUTHENTICATED", False), \
                patch.object(bot, "CONSENT_ENFORCEMENT", True), \
                patch.object(bot, "REMOTE_STORAGE", None), \
                patch.object(bot, "BASE_DIR", temp_dir), \
                patch.object(bot, "TENANT_REGISTRY_FILE", os.path.join(temp_dir, "teacher_registry.json")), \
                patch.object(bot, "CONSENT_LEDGER_FILE", os.path.join(temp_dir, "consent_ledger.json")), \
                patch.object(bot, "DATA_FILE", os.path.join(temp_dir, "schedule.json")), \
                patch.object(bot, "STUDENTS_FILE", os.path.join(temp_dir, "students.json")), \
                patch.object(bot, "SETTINGS_FILE", os.path.join(temp_dir, "settings.json")), \
                patch.object(bot, "validate_init_data", return_value=(True, {"id": 123, "first_name": "T"})):
            client = bot.flask_app.test_client()
            headers = {"X-Telegram-Init-Data": "signed"}
            blocked = client.get("/api/get_students", headers=headers)
            self.assertEqual(blocked.status_code, 428)
            self.assertEqual(blocked.get_json()["code"], "consent_required")

            accepted = client.post("/api/consent/accept", headers=headers, json={"documents": list(DOC_ENV_KIND)})
            self.assertEqual(accepted.status_code, 200)
            self.assertTrue(accepted.get_json()["ready"])
            self.assertEqual(client.get("/api/get_students", headers=headers).status_code, 200)

            revoked = client.post("/api/consent/revoke", headers=headers, json={"documents": ["personal_data_consent"]})
            self.assertEqual(revoked.status_code, 200)
            self.assertFalse(revoked.get_json()["ready"])
            self.assertEqual(client.get("/api/get_students", headers=headers).status_code, 428)
            with open(os.path.join(temp_dir, "consent_ledger.json"), encoding="utf-8") as source:
                ledger = json.load(source)
            self.assertEqual([event["action"] for event in ledger["events"]], ["accepted", "accepted", "revoked"])
            self.assertNotIn("initData", json.dumps(ledger))

    def test_default_enforcement_off_does_not_change_existing_api(self):
        with tempfile.TemporaryDirectory() as temp_dir, \
                patch.object(bot, "ALLOW_UNAUTHENTICATED", False), \
                patch.object(bot, "CONSENT_ENFORCEMENT", False), \
                patch.object(bot, "REMOTE_STORAGE", None), \
                patch.object(bot, "BASE_DIR", temp_dir), \
                patch.object(bot, "TENANT_REGISTRY_FILE", os.path.join(temp_dir, "teacher_registry.json")), \
                patch.object(bot, "DATA_FILE", os.path.join(temp_dir, "schedule.json")), \
                patch.object(bot, "STUDENTS_FILE", os.path.join(temp_dir, "students.json")), \
                patch.object(bot, "SETTINGS_FILE", os.path.join(temp_dir, "settings.json")), \
                patch.object(bot, "validate_init_data", return_value=(True, {"id": 456})):
            response = bot.flask_app.test_client().get("/api/get_students", headers={"X-Telegram-Init-Data": "signed"})
            self.assertEqual(response.status_code, 200)


DOC_ENV_KIND = ("user_agreement", "personal_data_consent")

if __name__ == "__main__":
    unittest.main()
