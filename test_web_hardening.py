import hashlib
import hmac
import io
import json
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

import bot
from PIL import Image


def signed_init_data(token, auth_date):
    values = {"auth_date": str(auth_date), "user": json.dumps({"id": 123})}
    check = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


class WebHardeningTests(unittest.TestCase):
    def setUp(self):
        with bot._rate_lock:
            bot._rate_windows.clear()

    def test_init_data_default_ttl_is_fifteen_minutes(self):
        token = "123456:unit-test-token"
        now = int(time.time())
        with patch.object(bot, "TOKEN", token), patch.object(bot, "ALLOW_UNAUTHENTICATED", False):
            self.assertTrue(bot.validate_init_data(signed_init_data(token, now - 899))[0])
            self.assertFalse(bot.validate_init_data(signed_init_data(token, now - 901))[0])
            self.assertFalse(bot.validate_init_data(signed_init_data(token, now + 31))[0])

    def test_security_headers_are_global(self):
        response = bot.flask_app.test_client().get("/app/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
        self.assertEqual(
            response.headers["Permissions-Policy"],
            "camera=(), microphone=(), geolocation=(), payment=()",
        )
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    def test_rate_limit_returns_generic_429(self):
        client = bot.flask_app.test_client()
        with patch.object(bot, "ALLOW_UNAUTHENTICATED", True), patch.dict(
            bot._RATE_LIMITS, {"read": (1, 60.0)}
        ):
            first = client.get("/api/get_students")
            second = client.get("/api/get_students")
        self.assertNotEqual(first.status_code, 429)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.get_json(), {
            "status": "error", "message": "Слишком много запросов. Повторите позже."
        })
        self.assertEqual(second.headers["Retry-After"], "60")

    def test_global_request_size_limit(self):
        client = bot.flask_app.test_client()
        with patch.object(bot, "ALLOW_UNAUTHENTICATED", True), patch.object(
            bot.flask_app, "config", {**bot.flask_app.config, "MAX_CONTENT_LENGTH": 32}
        ):
            response = client.post(
                "/api/upload_receipt_asset",
                data={"asset_type": "logo", "file": (io.BytesIO(b"x" * 100), "x.png")},
                content_type="multipart/form-data",
            )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.get_json()["message"], "Запрос слишком большой.")

    def test_image_content_not_extension_is_validated_and_reencoded(self):
        source = io.BytesIO()
        Image.new("RGB", (4, 3), (200, 10, 20)).save(source, format="PNG")
        extension, normalized = bot.normalize_uploaded_image(source.getvalue())
        self.assertEqual(extension, ".png")
        self.assertTrue(normalized.startswith(b"\x89PNG\r\n\x1a\n"))
        with Image.open(io.BytesIO(normalized)) as decoded:
            self.assertEqual(decoded.size, (4, 3))
            self.assertNotIn("exif", decoded.info)
        with self.assertRaises(ValueError):
            bot.normalize_uploaded_image(b"not an image")

    def test_image_pixel_cap_is_enforced_before_decode(self):
        source = io.BytesIO()
        Image.new("RGB", (11, 10)).save(source, format="PNG")
        with patch.object(bot, "MAX_IMAGE_PIXELS", 100), self.assertRaises(ValueError):
            bot.normalize_uploaded_image(source.getvalue())


if __name__ == "__main__":
    unittest.main()
