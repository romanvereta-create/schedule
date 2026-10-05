"""English launch surface, export, and deletion-request regressions."""
import io
import json
import os
import unittest
import zipfile
from unittest.mock import patch

import bot
import test_storage


class LaunchPackTests(unittest.TestCase):
    def setUp(self):
        test_storage.StorageSafetyTests.setUp(self)
        self.original_consent_file = bot.CONSENT_LEDGER_FILE
        bot.CONSENT_LEDGER_FILE = os.path.join(bot.BASE_DIR, "consent_ledger.json")
        bot.OWNER_ID = "teacher"
        bot.ensure_teacher_registered("teacher", {
            "id": "teacher", "first_name": "Alex", "username": "alex_tutor",
        })
        with bot.teacher_scope("teacher"):
            bot.save_json(bot.DATA_FILE, {"2026-10-05": [{"id": "l1", "student_name": "Maya"}]})
            bot.save_json(bot.STUDENTS_FILE, {"s1": {"name": "Maya", "phone": "+10000000000"}})
            bot.save_json(bot.SETTINGS_FILE, {
                "language": "en", "currency": "USD", "bot_token": "super-secret-value",
            })
            bot.save_json(bot.payments_file(), {"p1": {"amount": 40}})
        with bot._rate_lock:
            bot._rate_windows.clear()

    def tearDown(self):
        bot.CONSENT_LEDGER_FILE = self.original_consent_file
        test_storage.StorageSafetyTests.tearDown(self)

    def test_public_launch_pages_and_screenshots_are_served(self):
        client = bot.flask_app.test_client()
        for path in ("/", "/demo/", "/terms", "/privacy", "/screenshots/temli-calendar.png"):
            self.assertEqual(client.get(path).status_code, 200, path)
        self.assertEqual(client.get("/screenshots/not-allowed.png").status_code, 404)

    def test_account_export_is_portable_and_excludes_credentials(self):
        client = bot.flask_app.test_client()
        with patch.object(bot, "ALLOW_UNAUTHENTICATED", True):
            response = client.get("/api/export_account_data")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/zip")
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {"README.txt", "account.json", "payments.json", "schedule.json", "settings.json", "students.json"},
            )
            exported = b"\n".join(archive.read(name) for name in archive.namelist())
            self.assertIn(b"Maya", exported)
            self.assertNotIn(b"super-secret-value", exported)

    def test_deletion_request_requires_exact_confirmation_and_returns_reference(self):
        client = bot.flask_app.test_client()
        with patch.object(bot, "ALLOW_UNAUTHENTICATED", True):
            rejected = client.post("/api/request_account_deletion", json={"confirmation": "delete"})
            accepted = client.post("/api/request_account_deletion", json={"confirmation": "DELETE TEMLI"})
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(accepted.status_code, 200)
        reference = accepted.get_json()["reference"]
        self.assertRegex(reference, r"^DEL-[0-9A-F]{10}$")
        with open(os.path.join(bot.BASE_DIR, "account_deletion_requests.json"), encoding="utf-8") as source:
            stored = json.load(source)
        self.assertEqual(stored["teacher"]["reference"], reference)


if __name__ == "__main__":
    unittest.main()
