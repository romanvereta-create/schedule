import os
import io
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from telegram.request import HTTPXRequest
from production_server import ObservedTelegramRequest, TelegramDiagnostics
from telegram_transport import (telegram_proxy_url, validate_proxy_environment,
                                check_telegram_target, telegram_json, TelegramTransportError)


class ProxyConfigTests(unittest.TestCase):
    def test_storage_does_not_use_telegram_proxy(self):
        from remote_storage import RemoteJsonStorage
        with patch.dict(os.environ, {"TELEGRAM_PROXY_URL": "socks5://proxy:1080"}), \
                patch("remote_storage.httpx.Client") as direct:
            response = direct.return_value.post.return_value
            response.status_code = 200
            response.content = b'{"status":"ok","exists":true,"data":{},"version":"1"}'
            storage = RemoteJsonStorage("https://storage.example", "x" * 40)
            self.assertEqual(storage.read_json("test.json", {}), {})
            self.assertEqual(direct.call_args.kwargs["base_url"], "https://storage.example")
            self.assertFalse(direct.call_args.kwargs["trust_env"])
            self.assertNotIn("proxy", direct.call_args.kwargs)
            direct.return_value.post.assert_called_once()

    def test_supported_urls_and_absent(self):
        for value in ("", "http://user:pass@proxy.example:3128",
                      "https://proxy.example:443", "socks5://proxy.example:1080",
                      "socks5h://user:pass@[::1]:1080"):
            with self.subTest(value=value), patch.dict(os.environ, {"TELEGRAM_PROXY_URL": value}, clear=True):
                self.assertEqual(validate_proxy_environment(), value or None)

    def test_invalid_config_is_secret_safe(self):
        for value in ("ftp://SECRET@host:21", "http://host", "http://host:bad",
                      "http://host:80/path", "http://host:80?SECRET", "http://host:80#SECRET"):
            with patch.dict(os.environ, {"TELEGRAM_PROXY_URL": value}, clear=True):
                with self.assertRaisesRegex(TelegramTransportError, "^invalid_TELEGRAM_PROXY_URL$"):
                    telegram_proxy_url()

    def test_global_proxies_rejected(self):
        for name in ("HTTP_PROXY", "https_proxy", "ALL_PROXY"):
            with patch.dict(os.environ, {name: "http://SECRET@host:80"}, clear=True):
                with self.assertRaises(TelegramTransportError) as caught:
                    validate_proxy_environment()
                self.assertNotIn("SECRET", str(caught.exception))

    def test_only_telegram_target_and_no_files(self):
        for url in ("https://storage.example/v1/json", "http://api.telegram.org/botTOKEN/getMe",
                    "https://api.telegram.org.evil/botTOKEN/getMe",
                    "https://api.telegram.org/file/botTOKEN/a.pdf"):
            with self.assertRaises(TelegramTransportError):
                check_telegram_target(url, "http://proxy:80")
        for method in ("sendDocument", "sendPhoto", "getFile"):
            with self.assertRaisesRegex(TelegramTransportError, "files_disabled"):
                check_telegram_target(f"https://api.telegram.org/botTOKEN/{method}", "http://proxy:80")
        check_telegram_target("https://api.telegram.org/botTOKEN/sendDocument", None)
        with self.assertRaises(TelegramTransportError):
            check_telegram_target("https://api.telegram.org/botTOKEN/setWebhook",
                                  "http://proxy:80", SimpleNamespace(multipart_data={"file": b"data"}))

    def test_sync_uses_explicit_proxy_and_no_redirects(self):
        with patch.dict(os.environ, {"TELEGRAM_PROXY_URL": "http://proxy:80"}, clear=True), \
                patch("telegram_transport.httpx.Client") as client:
            response = client.return_value.__enter__.return_value.post.return_value
            response.status_code = 200
            response.json.return_value = {"ok": True, "result": True}
            self.assertTrue(telegram_json("TOKEN", "deleteWebhook")["ok"])
            client.assert_called_once_with(proxy="http://proxy:80", trust_env=False,
                                           follow_redirects=False, timeout=10)

    def test_failed_proxy_has_no_direct_fallback_or_secret(self):
        with patch.dict(os.environ, {"TELEGRAM_PROXY_URL": "http://SECRET@proxy:80"}, clear=True), \
                patch("telegram_transport.httpx.Client", side_effect=httpx.ProxyError("SECRET")) as client:
            with self.assertRaises(TelegramTransportError) as caught:
                telegram_json("TOKEN", "getMe")
            self.assertEqual(str(caught.exception), "telegram_unavailable")
            self.assertEqual(client.call_count, 1)

    def test_personal_and_alert_paths_share_transport(self):
        import personal_bots
        import backup_alerts
        with patch.object(personal_bots, "telegram_json", return_value={"ok": True, "result": True}) as send:
            self.assertTrue(personal_bots.telegram_info("TOKEN", "deleteWebhook"))
            send.assert_called_once()
        with patch.object(backup_alerts, "telegram_json", return_value={"ok": True}) as send:
            self.assertTrue(backup_alerts.send_owner(SimpleNamespace(TOKEN="TOKEN", OWNER_ID=1), "test"))
            send.assert_called_once()


class AsyncProxyTests(unittest.IsolatedAsyncioTestCase):
    async def test_polling_and_regular_clients_use_proxy(self):
        for options in ({}, {"connection_pool_size": 1, "read_timeout": 45}):
            with patch.dict(os.environ, {"TELEGRAM_PROXY_URL": "http://proxy:80"}):
                client = ObservedTelegramRequest(TelegramDiagnostics(), **options)
                try:
                    self.assertEqual(client.telegram_proxy, "http://proxy:80")
                    self.assertFalse(client._client._trust_env)
                    self.assertFalse(client._client.follow_redirects)
                    with patch.object(HTTPXRequest, "do_request", new=AsyncMock(return_value=(200, b'{}'))) as send:
                        await client.do_request("https://api.telegram.org/botTOKEN/getUpdates", "POST")
                        send.assert_awaited_once()
                        with self.assertRaises(TelegramTransportError):
                            await client.do_request("https://storage.example/v1/json", "POST")
                        self.assertEqual(send.await_count, 1)
                finally:
                    await client.shutdown()

    async def test_socks_clients_construct(self):
        for scheme in ("socks5", "socks5h"):
            with patch.dict(os.environ, {"TELEGRAM_PROXY_URL": f"{scheme}://proxy:1080"}):
                client = ObservedTelegramRequest(TelegramDiagnostics())
                await client.shutdown()


if __name__ == "__main__":
    unittest.main()
