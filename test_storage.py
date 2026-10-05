import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import bot


class StorageSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = self.temp_dir.name
        self.originals = {
            name: getattr(bot, name)
            for name in (
                "BASE_DIR", "DATA_FILE", "STUDENTS_FILE", "SETTINGS_FILE",
                "BOOK_FILE", "TENANT_DATA_DIR", "TENANT_REGISTRY_FILE",
                "OWNER_ID", "DATA_LOCK",
            )
        }
        bot.BASE_DIR = root
        bot.DATA_FILE = os.path.join(root, "schedule.json")
        bot.STUDENTS_FILE = os.path.join(root, "students.json")
        bot.SETTINGS_FILE = os.path.join(root, "settings.json")
        bot.BOOK_FILE = os.path.join(root, "book.xlsx")
        bot.TENANT_DATA_DIR = os.path.join(root, "teacher_data")
        bot.TENANT_REGISTRY_FILE = os.path.join(root, "teacher_registry.json")
        bot.OWNER_ID = ""
        bot.DATA_LOCK = bot.InterProcessRLock(os.path.join(root, ".schedule_data.lock"))

    def tearDown(self):
        for name, value in self.originals.items():
            setattr(bot, name, value)
        self.temp_dir.cleanup()

    def test_corrupt_json_is_not_replaced_or_overwritten(self):
        with open(bot.DATA_FILE, "w", encoding="utf-8") as target:
            target.write("{broken")

        with self.assertRaises(bot.DataCorruptionError):
            bot.load_json(bot.DATA_FILE, {})
        with self.assertRaises(bot.DataCorruptionError):
            bot.save_json(bot.DATA_FILE, {"2026-09-04": []})

        with open(bot.DATA_FILE, "r", encoding="utf-8") as source:
            self.assertEqual(source.read(), "{broken")

    def test_save_keeps_last_valid_backup(self):
        bot.save_json(bot.DATA_FILE, {"version": 1})
        bot.save_json(bot.DATA_FILE, {"version": 2})

        with open(f"{bot.DATA_FILE}.bak", "r", encoding="utf-8") as source:
            self.assertEqual(json.load(source), {"version": 1})

    def test_legacy_data_requires_explicit_owner(self):
        with open(bot.DATA_FILE, "w", encoding="utf-8") as target:
            json.dump({"2026-09-04": []}, target)

        with self.assertRaisesRegex(RuntimeError, "SCHEDULE_OWNER_ID"):
            bot.ensure_teacher_registered("unexpected-user")

    def test_teacher_files_are_isolated_from_primary_files(self):
        bot.OWNER_ID = "primary"
        bot.ensure_teacher_registered("primary")
        bot.ensure_teacher_registered("secondary")

        with bot.teacher_scope("primary"):
            bot.save_json(bot.DATA_FILE, {"owner": "primary"})
        with bot.teacher_scope("secondary"):
            bot.save_json(bot.DATA_FILE, {"owner": "secondary"})

        with open(bot.DATA_FILE, "r", encoding="utf-8") as source:
            self.assertEqual(json.load(source)["owner"], "primary")
        secondary_file = os.path.join(bot.TENANT_DATA_DIR, "secondary", "schedule.json")
        with open(secondary_file, "r", encoding="utf-8") as source:
            self.assertEqual(json.load(source)["owner"], "secondary")

    def test_invalid_series_is_rejected_before_student_is_created(self):
        bot.OWNER_ID = "primary"
        bot.ensure_teacher_registered("primary")
        with bot.teacher_scope("primary"):
            bot.save_json(bot.DATA_FILE, {})
            bot.save_json(bot.STUDENTS_FILE, {})
            payload = {
                "date": "2026-09-04", "time": "12:00", "duration": 60,
                "lesson_type": "student", "student": "Анна", "student_id": "manual",
                "price": 1500, "repeat": "year", "repeat_until": "2026-08-01",
            }
            with bot.flask_app.test_request_context(json=payload):
                _response, status = bot.add_lesson()

            self.assertEqual(status, 400)
            self.assertEqual(bot.load_json(bot.DATA_FILE), {})
            self.assertEqual(bot.load_json(bot.STUDENTS_FILE), {})

    def test_series_longer_than_one_year_is_rejected(self):
        bot.OWNER_ID = "primary"
        bot.ensure_teacher_registered("primary")
        with bot.teacher_scope("primary"):
            payload = {
                "date": "2026-09-04", "time": "12:00", "duration": 60,
                "lesson_type": "student", "student": "Анна", "student_id": "manual",
                "price": 1500, "repeat": "year", "repeat_until": "2099-05-31",
            }
            with bot.flask_app.test_request_context(json=payload):
                _response, status = bot.add_lesson()

            self.assertEqual(status, 400)
            self.assertFalse(os.path.exists(bot.DATA_FILE))
            self.assertFalse(os.path.exists(bot.STUDENTS_FILE))

    def test_valid_school_year_series_is_created_weekly(self):
        bot.OWNER_ID = "primary"
        bot.ensure_teacher_registered("primary")
        with bot.teacher_scope("primary"):
            payload = {
                "date": "2026-09-04", "time": "12:00", "duration": 60,
                "lesson_type": "student", "student": "Анна", "student_id": "manual",
                "price": 1500, "repeat": "year", "repeat_until": "2027-05-31",
            }
            with bot.flask_app.test_request_context(json=payload):
                response = bot.add_lesson()

            self.assertEqual(response.get_json()["status"], "ok")
            schedule = bot.load_json(bot.DATA_FILE)
            self.assertEqual(min(schedule), "2026-09-04")
            self.assertEqual(max(schedule), "2027-05-28")
            self.assertEqual(sum(len(lessons) for lessons in schedule.values()), 39)
            series_ids = {lesson.get("series_id") for lessons in schedule.values() for lesson in lessons}
            self.assertEqual(len(series_ids), 1)

    def test_add_lesson_saves_contacts_and_returns_exact_student_id(self):
        bot.OWNER_ID = "primary"
        bot.ensure_teacher_registered("primary")
        with bot.teacher_scope("primary"):
            payload = {
                "date": "2026-09-12", "time": "18:00", "duration": 60,
                "lesson_type": "student", "student": "Новый ученик", "student_id": "manual",
                "price": 1500, "repeat": "no",
                "student_contacts": {"tg": "@student_new"},
                "contacts": {"tg": "@parent_new", "phone": "+79990000000"},
            }
            with bot.flask_app.test_request_context(json=payload):
                response = bot.add_lesson()

            result = response.get_json()
            student_id = result["student_id"]
            self.assertTrue(student_id.startswith("manual_"))
            students = bot.load_json(bot.STUDENTS_FILE)
            self.assertEqual(students[student_id]["student_contacts"], {"tg": "@student_new"})
            self.assertEqual(students[student_id]["contacts"], {"tg": "@parent_new", "phone": "+79990000000"})
            lesson = bot.load_json(bot.DATA_FILE)["2026-09-12"][0]
            self.assertEqual(lesson["student_id"], student_id)
    def test_non_finite_amounts_are_rejected(self):
        self.assertIsNone(bot.normalize_amount("NaN"))
        self.assertIsNone(bot.normalize_amount("Infinity"))
        self.assertEqual(bot.normalize_amount("1 500,50"), 1500.5)

    def test_non_finite_lesson_price_does_not_mutate_storage(self):
        bot.OWNER_ID = "primary"
        bot.ensure_teacher_registered("primary")
        with bot.teacher_scope("primary"):
            payload = {
                "date": "2026-09-04", "time": "12:00", "duration": 60,
                "lesson_type": "student", "student": "Анна", "student_id": "manual",
                "price": "NaN", "repeat": "no",
            }
            with bot.flask_app.test_request_context(json=payload):
                _response, status = bot.add_lesson()

            self.assertEqual(status, 400)
            self.assertFalse(os.path.exists(bot.DATA_FILE))
            self.assertFalse(os.path.exists(bot.STUDENTS_FILE))

    def test_payment_file_transaction_rolls_back_both_files(self):
        bot.OWNER_ID = "primary"
        bot.ensure_teacher_registered("primary")
        with bot.teacher_scope("primary"):
            bot.save_json(bot.DATA_FILE, {"state": "before"})
            with open(bot.BOOK_FILE, "wb") as target:
                target.write(b"book-before")

            with self.assertRaisesRegex(RuntimeError, "simulated failure"):
                with bot.payment_files_transaction():
                    bot.save_json(bot.DATA_FILE, {"state": "after"})
                    with open(bot.BOOK_FILE, "wb") as target:
                        target.write(b"book-after")
                    raise RuntimeError("simulated failure")

            self.assertEqual(bot.load_json(bot.DATA_FILE), {"state": "before"})
            with open(bot.BOOK_FILE, "rb") as source:
                self.assertEqual(source.read(), b"book-before")
            self.assertFalse(os.path.exists(bot.payment_transaction_paths()["marker"]))

    def test_abandoned_payment_transaction_is_recovered_after_restart(self):
        bot.OWNER_ID = "primary"
        bot.ensure_teacher_registered("primary")
        with bot.teacher_scope("primary"):
            bot.save_json(bot.DATA_FILE, {"state": "before"})
            with open(bot.BOOK_FILE, "wb") as target:
                target.write(b"book-before")
            paths = bot.payment_transaction_paths()
            bot._atomic_copy(bot.DATA_FILE, paths["schedule_backup"])
            bot._atomic_copy(bot.BOOK_FILE, paths["book_backup"])
            bot._save_json_raw(paths["marker"], {
                "schedule_existed": True,
                "book_existed": True,
                "created_at": "2026-09-04T16:00:00Z",
            })
            bot.save_json(bot.DATA_FILE, {"state": "partially-written"})
            with open(bot.BOOK_FILE, "wb") as target:
                target.write(b"book-partially-written")

            self.assertTrue(bot.recover_payment_transaction())

            self.assertEqual(bot.load_json(bot.DATA_FILE), {"state": "before"})
            with open(bot.BOOK_FILE, "rb") as source:
                self.assertEqual(source.read(), b"book-before")
            self.assertFalse(os.path.exists(paths["marker"]))
            self.assertFalse(os.path.exists(paths["schedule_backup"]))
            self.assertFalse(os.path.exists(paths["book_backup"]))

    def test_subscription_does_not_mark_lessons_when_book_write_fails(self):
        bot.OWNER_ID = "primary"
        bot.ensure_teacher_registered("primary")
        schedule = {
            "2026-09-10": [{
                "id": "lesson-1", "time": "10:00", "duration": 60,
                "lesson_type": "student", "student": "Анна",
                "student_id": "student-1", "price": 1000, "paid": False,
            }],
            "2026-09-17": [{
                "id": "lesson-2", "time": "10:00", "duration": 60,
                "lesson_type": "student", "student": "Анна",
                "student_id": "student-1", "price": 1000, "paid": False,
            }],
        }
        receipt_path = os.path.join(self.temp_dir.name, "receipt.pdf")
        with open(receipt_path, "wb") as target:
            target.write(b"pdf")

        with bot.teacher_scope("primary"):
            bot.save_json(bot.DATA_FILE, schedule)
            bot.save_json(bot.STUDENTS_FILE, {"student-1": {"name": "Анна"}})
            payload = {
                "date": "2026-09-10", "id": "lesson-1", "student_id": "student-1",
                "amount": 2000, "lesson_count": 2, "send_receipt": False,
            }
            with bot.flask_app.test_request_context(json=payload), \
                    patch.object(bot, "generate_receipt_pdf", return_value=(receipt_path, "test-receipt", bot.receipt_now())), \
                    patch.object(bot, "add_receipt_to_book", side_effect=OSError("book unavailable")):
                _response, status = bot.pay_subscription()

            self.assertEqual(status, 500)
            restored = bot.load_json(bot.DATA_FILE)
            self.assertFalse(restored["2026-09-10"][0]["paid"])
            self.assertFalse(restored["2026-09-17"][0]["paid"])

    def test_individual_payment_stays_unpaid_when_book_write_fails(self):
        bot.OWNER_ID = "primary"
        bot.ensure_teacher_registered("primary")
        schedule = {
            "2026-09-10": [{
                "id": "lesson-1", "time": "10:00", "duration": 60,
                "lesson_type": "student", "student": "Анна",
                "student_id": "student-1", "price": 1000, "paid": False,
            }],
        }
        receipt_path = os.path.join(self.temp_dir.name, "receipt.pdf")
        with open(receipt_path, "wb") as target:
            target.write(b"pdf")

        with bot.teacher_scope("primary"):
            bot.save_json(bot.DATA_FILE, schedule)
            bot.save_json(bot.STUDENTS_FILE, {"student-1": {"name": "Анна"}})
            payload = {"date": "2026-09-10", "id": "lesson-1", "paid": True, "send_receipt": False}
            with bot.flask_app.test_request_context(json=payload), \
                    patch.object(bot, "generate_receipt_pdf", return_value=(receipt_path, "test-receipt", bot.receipt_now())), \
                    patch.object(bot, "add_receipt_to_book", side_effect=OSError("book unavailable")):
                _response, status = bot.mark_paid()

            self.assertEqual(status, 500)
            restored = bot.load_json(bot.DATA_FILE)
            self.assertFalse(restored["2026-09-10"][0]["paid"])
            self.assertNotIn("receipt_number", restored["2026-09-10"][0])

    def test_group_payment_rolls_back_every_member_and_book(self):
        bot.OWNER_ID = "primary"
        bot.ensure_teacher_registered("primary")
        schedule = {
            "2026-09-10": [{
                "id": "group-1", "time": "10:00", "duration": 60,
                "lesson_type": "group", "student": "Группа", "group_name": "Группа",
                "paid": False,
                "group_members": [
                    {"student_id": "student-1", "name": "Анна", "price": 1000, "paid": False, "free": False},
                    {"student_id": "student-2", "name": "Борис", "price": 1000, "paid": False, "free": False},
                ],
            }],
        }
        students = {"student-1": {"name": "Анна"}, "student-2": {"name": "Борис"}}
        original_add_to_book = bot.add_receipt_to_book
        book_calls = 0

        def fake_receipt(_settings, client_name, _amount, lesson_id, **_kwargs):
            path = os.path.join(self.temp_dir.name, f"{lesson_id}.pdf")
            with open(path, "wb") as target:
                target.write(b"pdf")
            return path, f"receipt-{client_name}", bot.receipt_now()

        def fail_on_second_book_row(*args, **kwargs):
            nonlocal book_calls
            book_calls += 1
            if book_calls == 2:
                raise OSError("second row failed")
            return original_add_to_book(*args, **kwargs)

        with bot.teacher_scope("primary"):
            bot.save_json(bot.DATA_FILE, schedule)
            bot.save_json(bot.STUDENTS_FILE, students)
            payload = {
                "date": "2026-09-10", "id": "group-1", "paid": True,
                "paid_student_ids": ["student-1", "student-2"], "send_receipt": False,
            }
            with bot.flask_app.test_request_context(json=payload), \
                    patch.object(bot, "generate_receipt_pdf", side_effect=fake_receipt), \
                    patch.object(bot, "add_receipt_to_book", side_effect=fail_on_second_book_row):
                _response, status = bot.mark_paid()

            self.assertEqual(status, 500)
            restored_lesson = bot.load_json(bot.DATA_FILE)["2026-09-10"][0]
            self.assertFalse(restored_lesson["paid"])
            self.assertTrue(all(not member["paid"] for member in restored_lesson["group_members"]))
            self.assertFalse(os.path.exists(bot.BOOK_FILE))

    def test_direct_payment_reversal_adds_compensating_book_row(self):
        bot.OWNER_ID = "primary"
        bot.ensure_teacher_registered("primary")
        created_at = bot.receipt_now()
        schedule = {
            "2026-09-10": [{
                "id": "lesson-1", "time": "10:00", "duration": 60,
                "lesson_type": "student", "student": "Анна",
                "student_id": "student-1", "price": 1000, "paid": True,
                "receipt_number": "receipt-1", "receipt_created_at": created_at.isoformat(),
                "receipt_logged": True,
            }],
        }

        with bot.teacher_scope("primary"):
            bot.save_json(bot.DATA_FILE, schedule)
            bot.save_json(bot.STUDENTS_FILE, {"student-1": {"name": "Анна"}})
            bot.add_receipt_to_book("Анна", 1000, "receipt-1", created_at)
            with bot.flask_app.test_request_context(json={
                "date": "2026-09-10", "id": "lesson-1", "paid": False, "send_receipt": False,
            }):
                response = bot.mark_paid()

            self.assertEqual(response.get_json()["status"], "ok")
            restored = bot.load_json(bot.DATA_FILE)["2026-09-10"][0]
            self.assertFalse(restored["paid"])
            self.assertNotIn("receipt_number", restored)
            with open(bot.BOOK_FILE, "rb") as source:
                workbook = bot.openpyxl.load_workbook(bot.io.BytesIO(source.read()), data_only=True)
            try:
                rows = list(workbook.active.iter_rows(values_only=True))
            finally:
                workbook.close()
            self.assertEqual(rows[-1][2], "receipt-1")
            self.assertEqual(rows[-1][4], -1000)
            self.assertEqual(rows[-1][5], "Отмена оплаты занятия")

    def test_single_subscription_lesson_reversal_is_blocked(self):
        bot.OWNER_ID = "primary"
        bot.ensure_teacher_registered("primary")
        schedule = {
            "2026-09-10": [{
                "id": "lesson-1", "time": "10:00", "duration": 60,
                "lesson_type": "student", "student": "Анна",
                "student_id": "student-1", "price": 1000, "paid": True,
                "paid_via_subscription": "subscription-1",
            }],
        }
        with bot.teacher_scope("primary"):
            bot.save_json(bot.DATA_FILE, schedule)
            with bot.flask_app.test_request_context(json={
                "date": "2026-09-10", "id": "lesson-1", "paid": False, "send_receipt": False,
            }):
                _response, status = bot.mark_paid()

            self.assertEqual(status, 409)
            self.assertTrue(bot.load_json(bot.DATA_FILE)["2026-09-10"][0]["paid"])

    def test_group_member_reversal_adds_compensating_book_row(self):
        bot.OWNER_ID = "primary"
        bot.ensure_teacher_registered("primary")
        created_at = bot.receipt_now()
        schedule = {
            "2026-09-10": [{
                "id": "group-1", "time": "10:00", "duration": 60,
                "lesson_type": "group", "student": "Группа", "group_name": "Группа", "paid": True,
                "group_members": [
                    {
                        "student_id": "student-1", "name": "Анна", "price": 1000,
                        "paid": True, "free": False, "receipt_number": "receipt-1",
                        "receipt_created_at": created_at.isoformat(), "receipt_logged": True,
                    },
                    {"student_id": "student-2", "name": "Борис", "price": 1200, "paid": True, "free": False},
                ],
            }],
        }
        students = {"student-1": {"name": "Анна"}, "student-2": {"name": "Борис"}}

        with bot.teacher_scope("primary"):
            bot.save_json(bot.DATA_FILE, schedule)
            bot.save_json(bot.STUDENTS_FILE, students)
            bot.add_receipt_to_book("Анна", 1000, "receipt-1", created_at)
            with bot.flask_app.test_request_context(json={
                "date": "2026-09-10", "id": "group-1", "paid": True,
                "paid_student_ids": ["student-2"], "send_receipt": False,
            }):
                response = bot.mark_paid()

            self.assertEqual(response.get_json()["status"], "ok")
            restored = bot.load_json(bot.DATA_FILE)["2026-09-10"][0]
            self.assertFalse(restored["paid"])
            self.assertFalse(restored["group_members"][0]["paid"])
            self.assertTrue(restored["group_members"][1]["paid"])
            self.assertNotIn("receipt_number", restored["group_members"][0])
            with open(bot.BOOK_FILE, "rb") as source:
                workbook = bot.openpyxl.load_workbook(bot.io.BytesIO(source.read()), data_only=True)
            try:
                rows = list(workbook.active.iter_rows(values_only=True))
            finally:
                workbook.close()
            self.assertEqual(rows[-1][2], "receipt-1")
            self.assertEqual(rows[-1][4], -1000)
            self.assertEqual(rows[-1][5], "Отмена оплаты участника группы")


class ReminderLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_reminder_task_is_cancelled_on_stop(self):
        original_worker = bot.reminder_worker
        started = asyncio.Event()

        async def waiting_worker(_application):
            started.set()
            await asyncio.Event().wait()

        application = object()
        bot.reminder_worker = waiting_worker
        try:
            await bot.post_init(application)
            await started.wait()
            task = bot.REMINDER_TASK
            self.assertIsNotNone(task)
            self.assertFalse(task.done())

            await bot.post_stop(application)

            self.assertTrue(task.cancelled())
            self.assertIsNone(bot.REMINDER_TASK)
            self.assertIsNone(bot.BOT_APPLICATION)
            self.assertIsNone(bot.BOT_LOOP)
        finally:
            bot.reminder_worker = original_worker
            if bot.REMINDER_TASK is not None:
                bot.REMINDER_TASK.cancel()
                bot.REMINDER_TASK = None


if __name__ == "__main__":
    unittest.main()

