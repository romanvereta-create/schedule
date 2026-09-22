"""Replicate verified storage-service ZIP backups to Bot3 persistent storage."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import time
import zipfile
from pathlib import Path, PurePosixPath


BACKUP_NAME = re.compile(r"temli-\d{8}T\d{6}\d*Z-[a-z0-9-]+\.zip")
MAX_ARCHIVE_BYTES = 160 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
_RUN_LOCK = threading.Lock()


class ReplicaError(RuntimeError):
    pass


def configured_replica_dir(environ=None):
    """Return an explicit absolute replica directory, or None when disabled."""
    environ = os.environ if environ is None else environ
    raw = str(environ.get("TEMLI_REPLICA_DIR", "") or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        raise ReplicaError("TEMLI_REPLICA_DIR must be an absolute path")
    path = path.resolve()
    if path == Path(path.anchor):
        raise ReplicaError("TEMLI_REPLICA_DIR must not be a filesystem root")
    return path


def _positive_int(environ, name, default, *, minimum=1, maximum=1000000):
    try:
        value = int(environ.get(name, default))
    except (TypeError, ValueError):
        raise ReplicaError(name + " must be an integer") from None
    if value < minimum or value > maximum:
        raise ReplicaError(name + " is outside the allowed range")
    return value


def replica_settings(environ=None):
    environ = os.environ if environ is None else environ
    return {
        "retention": _positive_int(environ, "TEMLI_REPLICA_RETENTION", 30, maximum=1000),
        "interval": _positive_int(environ, "TEMLI_REPLICA_INTERVAL_SECONDS", 3600,
                                  minimum=60, maximum=604800),
    }


def verify_archive(raw, expected_sha256=None):
    """Verify the outer digest and every member declared by the ZIP manifest."""
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_ARCHIVE_BYTES:
        raise ReplicaError("invalid_backup_size")
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 and digest != expected_sha256:
        raise ReplicaError("backup_checksum_mismatch")
    try:
        import io
        with zipfile.ZipFile(io.BytesIO(raw), "r") as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            if (len(names) != len(set(names)) or "manifest.json" not in names
                    or any(item.is_dir() for item in infos)
                    or sum(item.file_size for item in infos) > MAX_UNCOMPRESSED_BYTES):
                raise ReplicaError("invalid_backup")
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            if (not isinstance(manifest, dict) or manifest.get("schema") not in (1, 2)
                    or not isinstance(manifest.get("files"), list)):
                raise ReplicaError("invalid_backup")
            expected = {"manifest.json"}
            seen = set()
            for entry in manifest["files"]:
                if not isinstance(entry, dict):
                    raise ReplicaError("invalid_backup")
                relative = str(entry.get("path", ""))
                part = PurePosixPath(relative)
                if (not relative or part.is_absolute() or ".." in part.parts or "." in part.parts
                        or "\\" in relative or ":" in relative or relative in seen
                        or len(relative) > 512):
                    raise ReplicaError("invalid_backup")
                seen.add(relative)
                member = "data/" + relative
                expected.add(member)
                payload = archive.read(member)
                if (len(payload) != entry.get("size")
                        or hashlib.sha256(payload).hexdigest() != entry.get("sha256")):
                    raise ReplicaError("invalid_backup")
                if part.suffix.lower() == ".json":
                    json.loads(payload.decode("utf-8"))
            if set(names) != expected:
                raise ReplicaError("invalid_backup")
    except ReplicaError:
        raise
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError,
            zipfile.BadZipFile, OSError):
        raise ReplicaError("invalid_backup") from None
    return digest, manifest


def _atomic_write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".replica-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _prune(directory, retention):
    archives = sorted(directory.glob("temli-*.zip"), key=lambda item: item.name, reverse=True)
    for path in archives[retention:]:
        if BACKUP_NAME.fullmatch(path.name) and path.is_file():
            path.unlink()


def replica_status(directory):
    """Return metadata only; archives were fully verified before atomic write."""
    directory = Path(directory).resolve()
    archives = sorted(
        (path for path in directory.glob("temli-*.zip")
         if BACKUP_NAME.fullmatch(path.name) and path.is_file()),
        key=lambda item: item.name,
        reverse=True,
    ) if directory.is_dir() else []
    latest_age = None
    if archives:
        latest_age = max(0, int(time.time() - archives[0].stat().st_mtime))
    return {"count": len(archives), "latest_age_seconds": latest_age}


def replicate_once(remote, directory, *, retention=30):
    """Download all missing valid archives; return a non-sensitive run summary."""
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    downloaded = skipped = 0
    with _RUN_LOCK:
        items = remote.list_backups()
        if not isinstance(items, list):
            raise ReplicaError("invalid_backup_list")
        candidates = sorted(
            (item for item in items if isinstance(item, dict) and item.get("valid") is not False),
            key=lambda item: str(item.get("name", "")), reverse=True,
        )[:retention]
        for item in reversed(candidates):
            name = str(item.get("name", ""))
            expected = str(item.get("sha256", ""))
            if not BACKUP_NAME.fullmatch(name) or not re.fullmatch(r"[0-9a-f]{64}", expected):
                raise ReplicaError("invalid_backup_list")
            target = directory / name
            if target.is_file():
                local_digest = hashlib.sha256(target.read_bytes()).hexdigest()
                if local_digest == expected:
                    skipped += 1
                    continue
            raw = remote.download_backup(name, max_bytes=MAX_ARCHIVE_BYTES)
            verify_archive(raw, expected)
            _atomic_write(target, raw)
            downloaded += 1
        _prune(directory, retention)
    return {"downloaded": downloaded, "skipped": skipped,
            "retained": replica_status(directory)["count"]}


def run_once_from_env(remote, environ=None):
    environ = os.environ if environ is None else environ
    directory = configured_replica_dir(environ)
    if directory is None:
        raise ReplicaError("TEMLI_REPLICA_DIR is required")
    settings = replica_settings(environ)
    return replicate_once(remote, directory, retention=settings["retention"])


def start_worker(remote, directory, *, interval=3600, retention=30):
    """Start an immediate then periodic replica worker."""
    stop = threading.Event()

    def run():
        while not stop.is_set():
            try:
                result = replicate_once(remote, directory, retention=retention)
                print("TEMLI backup replica: ok; downloaded=" + str(result["downloaded"])
                      + "; retained=" + str(result["retained"]), flush=True)
            except Exception as error:
                # Type only: never leak a URL, token, response body, or local contents.
                print("TEMLI backup replica failed: " + type(error).__name__, flush=True)
            if stop.wait(interval):
                break

    thread = threading.Thread(target=run, name="temli-backup-replica", daemon=True)
    thread.start()
    return stop, thread


def main():
    from remote_storage import configured_remote_storage
    remote = configured_remote_storage()
    if remote is None:
        raise ReplicaError("remote storage is not configured")
    result = run_once_from_env(remote)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
