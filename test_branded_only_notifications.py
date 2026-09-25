import contextlib
import datetime
import os
import tempfile
import unittest
from unittest.mock import patch

import invitation_channels as channels
import personal_bots
import personal_notifications


class _Host:
    TOKEN = "999999:central-token"

    def __init__(self, root, personal_record, reminder_enabled=True, teacher_reminders=False):
        self.BASE_DIR = root
        self.DATA_LOCK = contextlib.nullcontext()
        self.STUDENTS_FILE = "students.json"
        self.DATA_FILE = "schedule.json"
        self._personal_record = personal_record
        self._reminder_enabled = reminder_enabled
        self._teacher_reminders = teacher_reminders
        self.saved = {}

    def registered_teacher_ids(self, include_legacy=True):
        return ["101"]

    def teacher_scope(self, teacher):
        return contextlib.nullcontext()

    def tenant_root(self):
        return self.BASE_DIR

    def recover_payment_transaction(self):
        pass

    def _load_json_raw(self, path, default=None):
        if path.endswith("personal_bots.json"):
            return {"101": self._personal_record} if self._personal_record else {}
        if path.endswith("personal_bot_links.json"):
            return {"bindings": {"binding": {
                "student_id": "anna", "role": "student", "state": "active",
                "connection_id": "brand-101", "chat_id": "700"
            }}}
        if path.endswith("personal_notification_log.json"):
            return self.saved.get(path, {})
        return default

    def _save_json_raw(self, path, value):
        self.saved[path] = value

    def load_settings(self):
        return {"language": "ru", "teacher_block_reminders": self._teacher_reminders,
                "teacher_block_reminder_minutes": 30, "teacher_block_gap_minutes": 60}

    def load_json(self, filename):
        if filename == self.STUDENTS_FILE:
            return {"anna": {"student_reminders": True}}
        return {"2026-09-08": [{
            "id": "lesson-1", "student_id": "anna", "time": "19:00",
            "duration": 60, "reminder_minutes": 60,
            "reminder_enabled": self._reminder_enabled,
        }]}

    @staticmethod
    def is_personal_event(lesson):
        return False

    @staticmethod
    def get_student_record(students, student_id):
        return students.get(student_id, {})


class BrandedOnlyTests(unittest.TestCase):
    def test_main_bot_is_never_available_or_preferred(self):
        host = _Host(".", None)
        main = channels.main_record(host)
        self.assertEqual(channels.records(host, None), {})
        self.assertEqual(channels.records(host, main), {})
        self.assertIsNone(channels.preferred(host, None))
        self.assertIsNone(channels.preferred(host, main))
        with self.assertRaisesRegex(personal_bots.ConnectionError, "bot_required"):
            channels.token_for(host, main)

    def test_legacy_main_invite_cannot_create_binding(self):
        host = _Host(".", None)
        reply = channels.accept_main(host, "join_101_" + "a" * 32,
                                     {"id": 700}, {"id": 700, "type": "private"}, 1)
        self.assertIn("больше не работает", reply)
        self.assertEqual(host.saved, {})

    def test_disabled_lesson_does_not_send_reminder(self):
        record = {"connection_id": "brand-101", "token": "encrypted"}
        with tempfile.TemporaryDirectory() as root:
            host = _Host(root, record, reminder_enabled=False)
            now = datetime.datetime(2026, 9, 8, 18, 1, tzinfo=datetime.timezone.utc)
            with patch.object(channels, "token_for", return_value="brand-token"), \
                    patch.object(personal_bots, "telegram_info") as send:
                personal_notifications.send_scheduled_notifications(host, now)
            send.assert_not_called()

    def test_enabled_lesson_uses_only_branded_token(self):
        record = {"connection_id": "brand-101", "token": "encrypted"}
        with tempfile.TemporaryDirectory() as root:
            host = _Host(root, record, reminder_enabled=True)
            now = datetime.datetime(2026, 9, 8, 18, 1, tzinfo=datetime.timezone.utc)
            with patch.object(channels, "token_for", return_value="brand-token"), \
                    patch.object(personal_bots, "telegram_info") as send:
                personal_notifications.send_scheduled_notifications(host, now)
            send.assert_called_once()
            self.assertEqual(send.call_args.args[0], "brand-token")
            self.assertNotEqual(send.call_args.args[0], host.TOKEN)

    def test_teacher_gets_one_reminder_for_a_consecutive_block(self):
        with tempfile.TemporaryDirectory() as root:
            host = _Host(root, None, teacher_reminders=True)
            host.load_json = lambda filename: ({"anna": {}} if filename == host.STUDENTS_FILE else {
                "2026-09-08": [
                    {"id": "one", "student": "Анна", "time": "10:00", "duration": 60},
                    {"id": "two", "student": "Борис", "time": "11:15", "duration": 60},
                ]
            })
            now = datetime.datetime(2026, 9, 8, 9, 31, tzinfo=datetime.timezone.utc)
            with patch.object(personal_bots, "telegram_info") as send:
                personal_notifications.send_scheduled_notifications(host, now)
            send.assert_called_once()
            self.assertEqual(send.call_args.args[0], host.TOKEN)
            self.assertEqual(send.call_args.args[2]["chat_id"], 101)

    def test_teacher_second_consecutive_lesson_has_no_reminder(self):
        with tempfile.TemporaryDirectory() as root:
            host = _Host(root, None, teacher_reminders=True)
            host.load_json = lambda filename: ({"anna": {}} if filename == host.STUDENTS_FILE else {
                "2026-09-08": [
                    {"id": "one", "student": "Анна", "time": "10:00", "duration": 60},
                    {"id": "two", "student": "Борис", "time": "11:15", "duration": 60},
                ]
            })
            now = datetime.datetime(2026, 9, 8, 10, 46, tzinfo=datetime.timezone.utc)
            with patch.object(personal_bots, "telegram_info") as send:
                personal_notifications.send_scheduled_notifications(host, now)
            send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
