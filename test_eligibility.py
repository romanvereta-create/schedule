"""Teacher eligibility regression tests."""
import unittest
from unittest.mock import patch

import bot
import test_storage


class EligibilityTests(unittest.TestCase):
    def setUp(self):
        test_storage.StorageSafetyTests.setUp(self)
        bot.OWNER_ID = "teacher"
        bot.ensure_teacher_registered("teacher", {"id": "teacher", "first_name": "Test"})
        with bot._rate_lock:
            bot._rate_windows.clear()

    def tearDown(self):
        test_storage.StorageSafetyTests.tearDown(self)

    def authenticated_client(self):
        return patch.object(bot, "validate_init_data", return_value=(True, {"id": "teacher"}))

    def test_teacher_must_accept_both_eligibility_statements(self):
        self.assertFalse(bot.teacher_eligibility_status("teacher")["ready"])
        with self.assertRaisesRegex(ValueError, "eligibility_not_confirmed"):
            bot.accept_teacher_eligibility("teacher", {
                "adult_private_tutor": True,
                "not_school_or_organization": False,
            })
        status = bot.accept_teacher_eligibility("teacher", {
            "adult_private_tutor": True,
            "not_school_or_organization": True,
        })
        self.assertTrue(status["ready"])
        stored = bot.load_tenant_registry()["teachers"]["teacher"]["eligibility"]
        self.assertEqual(stored["version"], bot.ELIGIBILITY_VERSION)
        self.assertTrue(stored["accepted_at"].endswith("Z"))

    def test_api_is_blocked_until_eligibility_is_accepted(self):
        client = bot.flask_app.test_client()
        with self.authenticated_client(), patch("invitation_channels.recipient_only", return_value=False), \
                patch.object(bot, "ELIGIBILITY_ENFORCEMENT", True), patch.object(bot, "ALLOW_UNAUTHENTICATED", False):
            blocked = client.get("/api/get_students", headers={"X-Telegram-Init-Data": "signed"})
            self.assertEqual(blocked.status_code, 428)
            self.assertEqual(blocked.get_json()["code"], "eligibility_required")

            accepted = client.post("/api/eligibility/accept", json={
                "adult_private_tutor": True,
                "not_school_or_organization": True,
            }, headers={"X-Telegram-Init-Data": "signed"})
            self.assertEqual(accepted.status_code, 200)
            self.assertTrue(accepted.get_json()["ready"])

            allowed = client.get("/api/get_students", headers={"X-Telegram-Init-Data": "signed"})
            self.assertEqual(allowed.status_code, 200)

if __name__ == "__main__":
    unittest.main()
