"""Regression checks for the isolated Bot3 Docker runtime."""

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
NODE_MANIFESTS = {
    "package.json",
    "package-lock.json",
    "npm-shrinkwrap.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "bun.lock",
    "bun.lockb",
}


class DockerContractTest(unittest.TestCase):
    def setUp(self):
        self.dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.instructions = [
            line.strip()
            for line in self.dockerfile.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]

    def test_python_image_and_exact_bot_entrypoint(self):
        self.assertRegex(self.instructions[0], r"(?i)^FROM\s+python:3\.11(?:[.-]|$)")

        commands = [
            line for line in self.instructions
            if re.match(r"(?i)^(CMD|ENTRYPOINT)\s+", line)
        ]
        self.assertEqual(len(commands), 1, "Dockerfile must have one runtime command")

        keyword, value = commands[0].split(None, 1)
        self.assertEqual(keyword.upper(), "CMD", "Bot3 must use the pinned CMD")
        self.assertEqual(json.loads(value), ["python", "-u", "bot.py"])

    def test_dockerfile_has_no_node_runtime_commands(self):
        executable = "\n".join(
            line for line in self.instructions
            if re.match(r"(?i)^(RUN|CMD|ENTRYPOINT)\s+", line)
        )
        self.assertNotRegex(
            executable,
            r"(?i)(?:^|[^a-z0-9_.-])(node|npm|npx|yarn|pnpm|bun)(?:$|[^a-z0-9_.-])",
        )

    def test_node_manifests_are_absent_and_ignored(self):
        present = sorted(name for name in NODE_MANIFESTS if (ROOT / name).exists())
        self.assertEqual(present, [], f"Node manifests are forbidden for Bot3: {present}")

        ignored = {
            line.strip()
            for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertEqual(NODE_MANIFESTS - ignored, set())


if __name__ == "__main__":
    unittest.main()
