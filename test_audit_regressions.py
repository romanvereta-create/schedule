"""Regression checks for the September storage audit; synthetic data only."""
import io
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import bot
import test_storage


class AuditRegressionTests(unittest.TestCase):
    def setUp(self):
        test_storage.StorageSafetyTests.setUp(self)
        self.originals["RECEIPT_ASSETS_DIR"] = bot.RECEIPT_ASSETS_DIR
        bot.RECEIPT_ASSETS_DIR = os.path.join(bot.BASE_DIR, "receipt_assets")
        bot.OWNER_ID = "audit"
        bot.ensure_teacher_registered("audit")

    def tearDown(self):
        test_storage.StorageSafetyTests.tearDown(self)

    def test_concurrent_settings_updates_preserve_both_fields(self):
        original = bot.load_settings
        first_read = threading.Event()
        second_read = threading.Event()
        def controlled_read():
            settings = original()
            if not first_read.is_set():
                first_read.set()
                second_read.wait(0.3)
            else:
                second_read.set()
            return settings
        def update(values):
            with bot.teacher_scope("audit"), bot.flask_app.test_request_context(json=values):
                return bot.update_settings().get_json()["status"]
        with patch.object(bot, "load_settings", side_effect=controlled_read):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(update, {"company_name": "saved company"})
                self.assertTrue(first_read.wait(3))
                second = pool.submit(update, {"phone": "saved phone"})
                self.assertEqual(first.result(timeout=5), "ok")
                self.assertEqual(second.result(timeout=5), "ok")
        with bot.teacher_scope("audit"):
            settings = original()
        self.assertEqual(settings["company_name"], "saved company")
        self.assertEqual(settings["phone"], "saved phone")

    def test_bot3_frontend_is_public_but_server_source_is_not(self):
        client = bot.flask_app.test_client()
        index = client.get("/app/")
        self.assertEqual(index.status_code, 200)
        self.assertIn(b'id="startup-status"', index.data)
        self.assertIn(b'id="startup-release"', index.data)
        self.assertEqual(index.headers.get("Cache-Control"), "no-store")
        app_script = client.get("/app/app.js")
        self.assertEqual(app_script.status_code, 200)
        self.assertIn(b"selfHostedBot3", app_script.data)
        self.assertEqual(app_script.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(client.get("/app/bot.py").status_code, 404)
        self.assertEqual(client.get("/app/../bot.py").status_code, 404)

    def test_health_exposes_only_public_release_identifier(self):
        response = bot.flask_app.test_client().get("/api/health")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["release"], bot.BOT3_RELEASE_ID)
        self.assertRegex(payload["release"], r"^[A-Za-z0-9._-]{1,64}$")
        self.assertIn("release-id-v1", payload["capabilities"])
        startup = bot.flask_app.test_client().get("/app/startup.js")
        self.assertIn(b"health.release", startup.data)

    def test_release_env_override_is_validated(self):
        with patch.dict(os.environ, {"TEMLI_RELEASE_ID": "bot3-2026.09.22"}):
            self.assertEqual(bot.resolve_public_release_id(), "bot3-2026.09.22")
        with patch.dict(os.environ, {"TEMLI_RELEASE_ID": "secret value with spaces"}):
            generated = bot.resolve_public_release_id()
        self.assertRegex(generated, r"^bot3-[0-9a-f]{12}$")

    def test_readiness_checks_authenticated_remote_storage(self):
        class ReadyStorage:
            def status(self):
                return {
                    "service": "temli-storage",
                    "backup": {
                        "count": 3,
                        "latest_age_seconds": 120,
                        "latest_verified": True,
                    },
                }

        client = bot.flask_app.test_client()
        with patch.object(bot, "REMOTE_STORAGE", ReadyStorage()):
            bot.READINESS_CACHE.update(
                expires_at=0.0, status_code=503, payload=None
            )
            response = client.get("/api/ready")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["storage"], "ok")
        self.assertEqual(payload["backup_count"], 3)
        self.assertEqual(payload["latest_backup_age_seconds"], 120)
        self.assertTrue(payload["latest_backup_verified"])
        self.assertFalse(payload["replica_enabled"])

    def test_recovery_marker_removed_while_waiting_is_not_corruption(self):
        with bot.teacher_scope("audit"):
            marker = Path(bot.payment_transaction_paths()["marker"])
            marker.write_text("{}")
            actual_lock = bot.DATA_LOCK
            class FinishedTransaction:
                def __enter__(self):
                    actual_lock.__enter__()
                    marker.unlink(missing_ok=True)
                def __exit__(self, *args):
                    return actual_lock.__exit__(*args)
            with patch.object(bot, "DATA_LOCK", FinishedTransaction()):
                self.assertFalse(bot.recover_payment_transaction())

    def test_failed_initial_workbook_write_leaves_no_partial_book(self):
        def fail_write(book, filename):
            Path(filename).write_bytes(b"partial zip")
            raise OSError("simulated disk failure")
        with bot.teacher_scope("audit"), patch.object(bot.openpyxl.Workbook, "save", fail_write):
            with self.assertRaises(OSError):
                bot.init_book()
            self.assertFalse(Path(bot.current_book_file()).exists())

    def test_failed_asset_replace_preserves_existing_bytes_and_settings(self):
        with bot.teacher_scope("audit"):
            assets = Path(bot.current_receipt_assets_dir())
            assets.mkdir()
            target = assets / "logo.png"
            target.write_bytes(b"original image")
            bot.save_json(bot.SETTINGS_FILE, {"receipt_logo": "logo.png"})
            before = Path(bot.tenant_file(bot.SETTINGS_FILE)).read_bytes()
            valid_image = io.BytesIO()
            bot.Image.new("RGB", (2, 2), "white").save(valid_image, format="PNG")
            valid_image.seek(0)
            with bot.flask_app.test_request_context(
                method="POST", data={"asset_type": "logo", "file": (valid_image, "new.png")},
                content_type="multipart/form-data"
            ), patch.object(bot.os, "replace", side_effect=OSError("simulated disk failure")):
                with self.assertRaises(OSError):
                    bot.upload_receipt_asset()
            self.assertEqual(target.read_bytes(), b"original image")
            self.assertEqual(Path(bot.tenant_file(bot.SETTINGS_FILE)).read_bytes(), before)
            self.assertFalse(list(assets.glob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
