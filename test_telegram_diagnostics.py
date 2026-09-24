import json
import unittest
from unittest.mock import AsyncMock, patch

from telegram.error import TimedOut
from telegram.request import HTTPXRequest
from production_server import TelegramDiagnostics, ObservedTelegramRequest


class TelegramDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_observation_preserves_result_and_hides_secrets(self):
        diagnostics = TelegramDiagnostics()
        client = ObservedTelegramRequest(diagnostics)
        result = (409, b'{"description":"conflict"}')
        try:
            with patch.object(HTTPXRequest, "do_request", new=AsyncMock(return_value=result)):
                self.assertEqual(await client.do_request(
                    "https://api.telegram.org/bot123:SECRET/getUpdates", "POST"), result)
            snapshot = diagnostics.snapshot()
            self.assertEqual(snapshot["requests"]["getUpdates"]["state"], "http_409")
            self.assertNotIn("SECRET", json.dumps(snapshot))
            self.assertNotIn("description", json.dumps(snapshot))
        finally:
            await client.shutdown()

    async def test_timeout_then_recovery_and_pending_visibility(self):
        diagnostics = TelegramDiagnostics()
        client = ObservedTelegramRequest(diagnostics)

        async def fail(**kwargs):
            self.assertEqual(diagnostics.snapshot()["requests"]["getMe"]["state"], "pending")
            raise TimedOut("sensitive error details")

        try:
            with patch.object(HTTPXRequest, "do_request", side_effect=fail):
                with self.assertRaises(TimedOut):
                    await client.do_request("https://api.telegram.org/bot123:SECRET/getMe", "POST")
            self.assertEqual(diagnostics.snapshot()["requests"]["getMe"]["state"], "TimedOut")
            with patch.object(HTTPXRequest, "do_request", new=AsyncMock(return_value=(200, b'{}'))):
                await client.do_request("https://api.telegram.org/bot123:SECRET/getMe", "POST")
            item = diagnostics.snapshot()["requests"]["getMe"]
            self.assertEqual(item["state"], "ok")
            self.assertEqual(item["attempts"], 2)
        finally:
            await client.shutdown()

    def test_unknown_operations_cannot_expose_url(self):
        diagnostics = TelegramDiagnostics()
        diagnostics.record("token-or-secret", "pending")
        self.assertEqual(diagnostics.snapshot()["requests"], {})


if __name__ == "__main__":
    unittest.main()
