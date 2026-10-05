import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import candidate_preflight as preflight


GOOD_ENV = {
    "TEMLI_DEPLOYMENT_ID": "temli-production-candidate",
    "SCHEDULE_BOT_TOKEN": "123456789:abcdefghijklmnopqrstuvwxyz_ABCDEF",
    "SCHEDULE_BOT_USERNAME": "TEMLI_Candidate_Bot",
    "SCHEDULE_OWNER_ID": "123456789",
    "SCHEDULE_TIMEZONE": "Europe/Moscow",
    "SCHEDULE_WEBAPP_URL": "https://candidate.example/app/",
    "SCHEDULE_WEBAPP_ORIGIN": "https://candidate.example",
    "TEMLI_STORAGE_URL": "https://storage-candidate.example/",
    "TEMLI_STORAGE_APP_TOKEN": "a" * 32,
    "TEMLI_STORAGE_BACKUP_READ_TOKEN": "b" * 32,
    "TEMLI_REPLICA_DIR": "/app/data/temli-storage-replica",
    "ALLOW_UNAUTHENTICATED": "false",
}

GOOD_DOCKERFILE = """\
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "-u", "bot.py"]
"""


class CandidatePreflightTests(unittest.TestCase):
    def make_root(self, dockerfile=GOOD_DOCKERFILE):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        (root / "Dockerfile").write_text(dockerfile, encoding="utf-8")
        self.addCleanup(temp.cleanup)
        return root

    def test_valid_candidate_passes(self):
        report = preflight.run_preflight(self.make_root(), GOOD_ENV)
        self.assertEqual(report["status"], "ok", report)
        self.assertTrue(all(item["status"] == "ok" for item in report["checks"]))

    def test_missing_environment_is_reported_by_name_only(self):
        secret = "123456789:abcdefghijklmnopqrstuvwxyz_ABCDEF"
        env = dict(GOOD_ENV)
        env.pop("SCHEDULE_OWNER_ID")
        env["SCHEDULE_BOT_TOKEN"] = secret
        report = preflight.run_preflight(self.make_root(), env)
        encoded = json.dumps(report)
        self.assertEqual(report["status"], "error")
        self.assertIn("SCHEDULE_OWNER_ID", encoded)
        self.assertNotIn(secret, encoded)

    def test_rejects_known_production_identity_and_host(self):
        env = dict(GOOD_ENV)
        env.update({
            "SCHEDULE_BOT_USERNAME": "@Schedule_Vereta_bot",
            "SCHEDULE_WEBAPP_URL": "https://bot-1787954043-4984-solo1986.bothost.tech/app/",
            "SCHEDULE_WEBAPP_ORIGIN": "https://bot-1787954043-4984-solo1986.bothost.tech",
        })
        report = preflight.run_preflight(self.make_root(), env)
        failures = {
            item["name"] for item in report["checks"] if item["status"] == "error"
        }
        self.assertIn("candidate_bot_identity", failures)
        self.assertIn("webapp_url", failures)

    def test_rejects_shared_frontend_or_non_https_storage(self):
        env = dict(GOOD_ENV)
        env["SCHEDULE_WEBAPP_URL"] = "https://romanvereta-create.github.io/app/"
        env["SCHEDULE_WEBAPP_ORIGIN"] = "https://romanvereta-create.github.io"
        env["TEMLI_STORAGE_URL"] = "http://storage-candidate.example"
        report = preflight.run_preflight(self.make_root(), env)
        failures = {
            item["name"] for item in report["checks"] if item["status"] == "error"
        }
        self.assertIn("webapp_url", failures)
        self.assertIn("storage_url", failures)

    def test_webapp_must_be_exact_app_path_and_matching_origin(self):
        for url, origin in (
            ("https://candidate.example/", "https://candidate.example"),
            ("https://candidate.example/app/?token=x", "https://candidate.example"),
            ("https://candidate.example/app/", "https://other.example"),
        ):
            with self.subTest(url=url, origin=origin):
                env = dict(GOOD_ENV)
                env["SCHEDULE_WEBAPP_URL"] = url
                env["SCHEDULE_WEBAPP_ORIGIN"] = origin
                report = preflight.run_preflight(self.make_root(), env)
                self.assertEqual(report["status"], "error")

    def test_candidate_identity_must_be_explicit(self):
        for identity in ("", "production", "bot3", "TEMLI Candidate"):
            with self.subTest(identity=identity):
                env = dict(GOOD_ENV)
                env["TEMLI_DEPLOYMENT_ID"] = identity
                report = preflight.run_preflight(self.make_root(), env)
                failure = next(
                    item for item in report["checks"]
                    if item["name"] == "candidate_identity"
                )
                self.assertEqual(failure["status"], "error")

    def test_storage_scopes_are_distinct_and_admin_is_absent(self):
        for updates in (
            {"TEMLI_STORAGE_BACKUP_READ_TOKEN": "a" * 32},
            {"TEMLI_STORAGE_ADMIN_TOKEN": "c" * 32},
            {"TEMLI_STORAGE_TOKEN": "l" * 32},
        ):
            with self.subTest(updates=tuple(updates)):
                env = dict(GOOD_ENV)
                env.update(updates)
                report = preflight.run_preflight(self.make_root(), env)
                self.assertEqual(report["status"], "error")

    def test_rejects_node_or_wrong_docker_entrypoint(self):
        for dockerfile in (
            'FROM node:20\nCMD ["node", "bot.py"]\n',
            'FROM python:3.11-slim\nCMD ["python", "bot.py"]\n',
            GOOD_DOCKERFILE + 'RUN npm install\n',
        ):
            with self.subTest(dockerfile=dockerfile):
                report = preflight.run_preflight(self.make_root(dockerfile), GOOD_ENV)
                check = report["checks"][0]
                self.assertEqual(check["name"], "docker_python_contract")
                self.assertEqual(check["status"], "error")

    def test_cli_output_never_prints_secrets(self):
        env = dict(GOOD_ENV)
        env["TEMLI_STORAGE_APP_TOKEN"] = "TOP-SECRET-STORAGE-TOKEN"
        env["SCHEDULE_BOT_TOKEN"] = "TOP-SECRET-BOT-TOKEN"
        output = io.StringIO()
        with patch.dict("os.environ", env, clear=True), redirect_stdout(output):
            code = preflight.main(["--root", str(self.make_root())])
        self.assertEqual(code, 1)
        self.assertNotIn("TOP-SECRET", output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["status"], "error")


if __name__ == "__main__":
    unittest.main()
