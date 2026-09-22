import json
import tempfile
import unittest
from pathlib import Path

import privacy_subject_report as report


class PrivacySubjectReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        tenant = self.root / "teacher_data" / "101"
        tenant.mkdir(parents=True)
        (self.root / "teacher_registry.json").write_text(
            json.dumps({"101": {"username": "private-name"}}), encoding="utf-8")
        (self.root / "personal_bots.json").write_text(
            json.dumps({"101": {"token": "secret-token"}}), encoding="utf-8")
        (tenant / "students.json").write_text(json.dumps({
            "s1": {"name": "Private Student", "telegram_id": 777},
            "s2": {"contacts": {"telegram": "777"}},
        }), encoding="utf-8")
        (tenant / "schedule.json").write_text(json.dumps({
            "2026-01-01": [{"student_id": "s1", "notes": "private note"}]
        }), encoding="utf-8")
        (tenant / "personal_bot_links.json").write_text(json.dumps({
            "invites": {}, "bindings": {"b1": {"chat_id": 777, "student_id": "s1"}}
        }), encoding="utf-8")
        (tenant / "personal_notification_log.json").write_text(
            json.dumps({"opaque-event": "sent"}), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_telegram_report_is_minimised_and_read_only(self):
        result = report.build_report(str(self.root), "telegram", "777", "k" * 32)
        encoded = json.dumps(result)
        self.assertEqual(result["mode"], "read_only")
        self.assertEqual(result["summary"]["files_with_matches"], 2)
        self.assertFalse(result["deletion_plan"]["automatic_deletion"])
        for secret in ("777", "Private Student", "private note", "secret-token"):
            self.assertNotIn(secret, encoded)

    def test_teacher_report_includes_owned_tenant_categories(self):
        result = report.build_report(str(self.root), "teacher", "101", "k" * 32)
        categories = {item["category"] for item in result["matches"]}
        self.assertIn("teacher_registry", categories)
        self.assertIn("personal_bot_metadata", categories)
        self.assertIn("students", categories)
        self.assertIn("schedules", categories)
        self.assertNotIn("101", json.dumps(result))

    def test_invalid_identifier_and_short_key_are_rejected(self):
        with self.assertRaises(ValueError):
            report.build_report(str(self.root), "telegram", "../777", "k" * 32)
        with self.assertRaises(ValueError):
            report.build_report(str(self.root), "telegram", "777", "short")
        with self.assertRaises(ValueError):
            report.build_report(str(self.root), "unsupported", "777", "k" * 32)

    def test_symlink_is_refused(self):
        target = self.root / "outside.json"
        target.write_text("{}", encoding="utf-8")
        link = self.root / "teacher_data" / "101" / "payments.json"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        with self.assertRaises(report.UnsafeStorage):
            report.build_report(str(self.root), "teacher", "101", "k" * 32)

    def test_malformed_json_fails_closed_without_content(self):
        bad = self.root / "teacher_data" / "101" / "payments.json"
        bad.write_text('{"card":"4111111111111111"', encoding="utf-8")
        with self.assertRaisesRegex(report.UnsafeStorage, "unreadable JSON: payments.json"):
            report.build_report(str(self.root), "teacher", "101", "k" * 32)


if __name__ == "__main__":
    unittest.main()
