import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from urllib.error import URLError

import check_bot3_postdeploy as smoke


GOOD_RESPONSES = {
    "/api/health": {
        "status": "ok",
        "storage": "remote-json-test",
        "release": "bot3-test-release",
        "capabilities": sorted(smoke.BOT_CAPABILITIES),
    },
    "/api/ready": {
        "status": "ok",
        "service": "temli-bot3",
        "storage": "ok",
        "storage_latency_ms": 249,
        "backup_count": 12,
        "latest_backup_age_seconds": 786,
        "latest_backup_verified": True,
    },
    "/health": {
        "status": "ok",
        "service": "temli-storage",
        "capabilities": sorted(smoke.STORAGE_CAPABILITIES),
    },
}


class PostDeployCheckTests(unittest.TestCase):
    def fetch_good(self, url, timeout):
        self.assertEqual(timeout, 3)
        for path, payload in GOOD_RESPONSES.items():
            if url.endswith(path):
                return copy.deepcopy(payload)
        self.fail("unexpected endpoint")

    def test_all_public_checks_pass(self):
        report = smoke.run_checks(
            "https://bot3.example",
            "https://storage.example",
            timeout=3,
            attempts=1,
            fetcher=self.fetch_good,
        )
        self.assertEqual(report["status"], "ok", report)
        self.assertEqual(list(report["checks"]), [
            "bot_health", "bot_ready", "storage_health",
        ])
        self.assertEqual(report["checks"]["bot_ready"]["details"]["backup_count"], 12)

    def test_missing_capability_fails(self):
        def fetch(url, timeout):
            payload = self.fetch_good(url, timeout)
            if url.endswith("/api/health"):
                payload["capabilities"].remove("readiness-v1")
            return payload

        report = smoke.run_checks(
            "https://bot3.example", "https://storage.example",
            timeout=3, attempts=1, fetcher=fetch,
        )
        self.assertEqual(report["status"], "error")
        self.assertIn("readiness-v1", report["checks"]["bot_health"]["error"])

    def test_ready_requires_remote_storage_and_backup(self):
        for changed in (
            {"storage": "local"},
            {"backup_count": 0},
            {"backup_count": True},
            {"storage_latency_ms": -1},
            {"latest_backup_age_seconds": -1},
            {"latest_backup_age_seconds": smoke.MAX_BACKUP_AGE_SECONDS + 1},
            {"latest_backup_verified": False},
        ):
            with self.subTest(changed=changed):
                payload = GOOD_RESPONSES["/api/ready"].copy()
                payload.update(changed)
                with self.assertRaises(smoke.CheckError):
                    smoke.validate_bot_ready(payload)

    def test_transient_failure_is_retried(self):
        calls = {}

        def fetch(url, timeout):
            calls[url] = calls.get(url, 0) + 1
            if calls[url] == 1:
                raise smoke.CheckError("network request failed or timed out")
            return self.fetch_good(url, timeout)

        report = smoke.run_checks(
            "https://bot3.example", "https://storage.example",
            timeout=3, attempts=2, fetcher=fetch,
        )
        self.assertEqual(report["status"], "ok", report)
        self.assertTrue(
            all(result["attempt"] == 2 for result in report["checks"].values()),
            report,
        )

    def test_urls_with_credentials_or_query_are_rejected(self):
        for url in (
            "https://token@example.test",
            "https://example.test?token=secret",
            "http://example.test",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                smoke.run_checks(url, "https://storage.example", fetcher=self.fetch_good)

    def test_network_error_does_not_echo_url_or_secret(self):
        secret = "do-not-print-this"

        def failing_opener(request, timeout):
            raise URLError(f"failure at {request.full_url}?token={secret}")

        with self.assertRaises(smoke.CheckError) as caught:
            smoke.fetch_json("https://example.test/health", 1, opener=failing_opener)
        self.assertNotIn(secret, str(caught.exception))
        self.assertNotIn("example.test", str(caught.exception))

    def test_main_prints_safe_json_and_returns_failure(self):
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = smoke.main(["--bot-base-url", "https://user:secret@example.test"])
        self.assertEqual(code, 1)
        report = json.loads(stream.getvalue())
        self.assertEqual(report["status"], "error")
        self.assertNotIn("secret", stream.getvalue())

    def test_timeout_and_attempt_bounds(self):
        for timeout in (0.1, 61):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                smoke.run_checks(
                    "https://bot3.example", "https://storage.example",
                    timeout=timeout, fetcher=self.fetch_good,
                )
        for attempts in (0, 6):
            with self.subTest(attempts=attempts), self.assertRaises(ValueError):
                smoke.run_checks(
                    "https://bot3.example", "https://storage.example",
                    attempts=attempts, fetcher=self.fetch_good,
                )


if __name__ == "__main__":
    unittest.main()
