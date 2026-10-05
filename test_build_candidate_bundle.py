import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import build_candidate_bundle as builder


class CandidateBundleTests(unittest.TestCase):
    def make_source(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for index, relative in enumerate(builder.RELEASE_FILES):
            path = root.joinpath(*relative.split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"release-content-{index}\n".encode())
        return root

    def test_bundle_is_deterministic_and_checksum_matches(self):
        source = self.make_source()
        output_a = source.parent / "candidate-a.zip"
        output_b = source.parent / "candidate-b.zip"
        self.addCleanup(lambda: output_a.unlink(missing_ok=True))
        self.addCleanup(lambda: output_b.unlink(missing_ok=True))
        self.addCleanup(lambda: output_a.with_name(output_a.name + ".sha256").unlink(missing_ok=True))
        self.addCleanup(lambda: output_b.with_name(output_b.name + ".sha256").unlink(missing_ok=True))

        report_a = builder.build_bundle(source, output_a)
        report_b = builder.build_bundle(source, output_b)

        self.assertEqual(output_a.read_bytes(), output_b.read_bytes())
        self.assertEqual(report_a["bundle_sha256"], builder._sha256(output_a.read_bytes()))
        self.assertEqual(report_a["release_id"], report_b["release_id"])
        checksum = output_a.with_name(output_a.name + ".sha256").read_text("ascii")
        self.assertEqual(checksum, f"{report_a['bundle_sha256']}  {output_a.name}\n")

    def test_manifest_covers_every_payload_file(self):
        source = self.make_source()
        output = source.parent / "candidate.zip"
        self.addCleanup(lambda: output.unlink(missing_ok=True))
        self.addCleanup(lambda: output.with_name(output.name + ".sha256").unlink(missing_ok=True))
        report = builder.build_bundle(source, output)

        with zipfile.ZipFile(output) as archive:
            names = archive.namelist()
            manifest_bytes = archive.read(builder.MANIFEST_NAME)
            manifest = json.loads(manifest_bytes)
            entries = {entry["path"]: entry for entry in manifest["files"]}
            self.assertEqual(names, sorted(builder.RELEASE_FILES) + [builder.MANIFEST_NAME])
            self.assertEqual(set(entries), set(builder.RELEASE_FILES))
            for relative in builder.RELEASE_FILES:
                data = archive.read(relative)
                self.assertEqual(entries[relative]["sha256"], builder._sha256(data))
                self.assertEqual(entries[relative]["size"], len(data))
            self.assertEqual(report["manifest_sha256"], builder._sha256(manifest_bytes))

    def test_unlisted_data_tests_repository_and_secrets_are_excluded(self):
        source = self.make_source()
        decoys = {
            "data/students.json": b'"private student"',
            ".git/config": b"repository metadata",
            "test_runtime.py": b"test data",
            ".env": b"SCHEDULE_BOT_TOKEN=secret",
            "client_secret.json": b'{"client_secret":"secret"}',
        }
        for relative, data in decoys.items():
            path = source.joinpath(*relative.split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        output = source.parent / "candidate.zip"
        self.addCleanup(lambda: output.unlink(missing_ok=True))
        self.addCleanup(lambda: output.with_name(output.name + ".sha256").unlink(missing_ok=True))

        builder.build_bundle(source, output)
        with zipfile.ZipFile(output) as archive:
            self.assertTrue(set(decoys).isdisjoint(archive.namelist()))

    def test_missing_required_file_fails_closed(self):
        source = self.make_source()
        (source / "bot.py").unlink()
        with self.assertRaisesRegex(builder.BuildError, "bot.py"):
            builder.build_bundle(source, source.parent / "candidate.zip")

    def test_secret_in_allowed_file_fails_closed(self):
        source = self.make_source()
        (source / "bot.py").write_text(
            'TOKEN = "123456789:abcdefghijklmnopqrstuvwxyz_ABCDEF"\n', encoding="utf-8"
        )
        with self.assertRaisesRegex(builder.BuildError, "Telegram bot token"):
            builder.build_bundle(source, source.parent / "candidate.zip")


if __name__ == "__main__":
    unittest.main()
