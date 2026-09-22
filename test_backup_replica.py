import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from backup_replica import (ReplicaError, configured_replica_dir, replicate_once,
                            replica_settings, replica_status, verify_archive)


def archive_bytes(value=b'{}'):
    manifest = {
        "schema": 2,
        "created_at": "2026-09-22T00:00:00+00:00",
        "reason": "automatic",
        "files": [{"path": "students.json", "size": len(value),
                   "sha256": hashlib.sha256(value).hexdigest()}],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("data/students.json", value)
    return buffer.getvalue()


class FakeRemote:
    def __init__(self, archives):
        self.archives = archives
        self.downloads = []

    def list_backups(self):
        return [{"name": name, "size": len(raw),
                 "sha256": hashlib.sha256(raw).hexdigest()}
                for name, raw in sorted(self.archives.items(), reverse=True)]

    def download_backup(self, name, *, max_bytes):
        self.downloads.append((name, max_bytes))
        return self.archives[name]


class BackupReplicaTests(unittest.TestCase):
    def test_disabled_without_explicit_directory_and_rejects_relative(self):
        self.assertIsNone(configured_replica_dir({}))
        with self.assertRaisesRegex(ReplicaError, "absolute"):
            configured_replica_dir({"TEMLI_REPLICA_DIR": "replicas"})
        with self.assertRaisesRegex(ReplicaError, "filesystem root"):
            configured_replica_dir({"TEMLI_REPLICA_DIR": str(Path(Path.cwd().anchor))})

    def test_settings_are_bounded(self):
        self.assertEqual(replica_settings({})["retention"], 30)
        with self.assertRaises(ReplicaError):
            replica_settings({"TEMLI_REPLICA_INTERVAL_SECONDS": "10"})

    def test_download_verify_atomic_skip_and_retention(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            archives = {
                "temli-20260922T000000000000Z-automatic.zip": archive_bytes(b'{"n":1}'),
                "temli-20260922T010000000000Z-automatic.zip": archive_bytes(b'{"n":2}'),
                "temli-20260922T020000000000Z-automatic.zip": archive_bytes(b'{"n":3}'),
            }
            remote = FakeRemote(archives)
            first = replicate_once(remote, directory, retention=2)
            self.assertEqual(first["downloaded"], 2)
            self.assertEqual(first["retained"], 2)
            self.assertFalse(list(directory.glob(".replica-*.tmp")))
            remote.downloads.clear()
            second = replicate_once(remote, directory, retention=2)
            self.assertEqual(second["downloaded"], 0)
            self.assertEqual(len(remote.downloads), 0)
            status = replica_status(directory)
            self.assertEqual(status["count"], 2)
            self.assertGreaterEqual(status["latest_age_seconds"], 0)

    def test_rejects_outer_checksum_and_tampered_manifest_payload(self):
        raw = archive_bytes(b'{"ok":true}')
        with self.assertRaisesRegex(ReplicaError, "checksum"):
            verify_archive(raw, "0" * 64)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            manifest = {"schema": 2, "files": [{"path": "students.json", "size": 2,
                                                  "sha256": "0" * 64}]}
            archive.writestr("manifest.json", json.dumps(manifest))
            archive.writestr("data/students.json", b'{}')
        with self.assertRaisesRegex(ReplicaError, "invalid_backup"):
            verify_archive(buffer.getvalue())

    def test_invalid_remote_metadata_writes_nothing(self):
        class InvalidRemote:
            def list_backups(self):
                return [{"name": "../escape.zip", "sha256": "0" * 64}]
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ReplicaError, "invalid_backup_list"):
                replicate_once(InvalidRemote(), temporary)
            self.assertFalse(list(Path(temporary).iterdir()))


if __name__ == "__main__":
    unittest.main()
