"""Install the pinned TEMLI candidate release into /app.

This is intentionally a small operator entrypoint for hosting consoles that
reject long one-line commands. It never reads or changes environment values,
the persistent data directory, or repository metadata.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath


PINNED_COMMIT = "61ba9efff30ba06f7fdd25a29b0c9fdee3b90344"
RAW_BASE = (
    "https://raw.githubusercontent.com/romanvereta-create/schedule/"
    + PINNED_COMMIT
    + "/"
)
RELEASE_FILES = (
    "DejaVuSansCondensed-Bold.ttf",
    "DejaVuSansCondensed.ttf",
    "Dockerfile",
    "app.js",
    "automatic_backup.py",
    "backup_alerts.py",
    "backup_replica.py",
    "bot.py",
    "calendar_undo.py",
    "consent_ledger.py",
    "help.js",
    "i18n.js",
    "index.html",
    "invitation_channels.py",
    "locales/en.js",
    "persistent_storage.py",
    "personal_bot_invites.py",
    "personal_bots.py",
    "personal_notifications.js",
    "personal_notifications.py",
    "production_server.py",
    "remote_storage.py",
    "requirements.txt",
    "startup.js",
    "styles.css",
    "support.js",
    "ux.css",
    "ux.js",
    "vendor/telegram-web-app.js",
    "verify_live_storage.py",
)
MAX_FILE_BYTES = 8 * 1024 * 1024


class BootstrapError(RuntimeError):
    pass


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "temli-candidate-bootstrap/1"})
    with urllib.request.urlopen(request, timeout=45) as response:
        data = response.read(MAX_FILE_BYTES + 1)
    if not data or len(data) > MAX_FILE_BYTES:
        raise BootstrapError("invalid release file size")
    return data


def _safe_target(root: Path, relative: str) -> Path:
    item = PurePosixPath(relative)
    if item.is_absolute() or ".." in item.parts or "\\" in relative:
        raise BootstrapError("invalid release path")
    target = root.joinpath(*item.parts)
    parent = target.parent.resolve()
    try:
        parent.relative_to(root)
    except ValueError:
        raise BootstrapError("unsafe release path")
    if target.is_symlink():
        raise BootstrapError("unsafe release path")
    return target


def install(root: Path, downloader=_download) -> dict[str, object]:
    root = root.resolve()
    if not root.is_dir():
        raise BootstrapError("target directory does not exist")
    staged: list[tuple[Path, Path]] = []
    try:
        for relative in RELEASE_FILES:
            target = _safe_target(root, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            payload = downloader(RAW_BASE + relative)
            fd, temporary_name = tempfile.mkstemp(
                prefix="." + target.name + ".", suffix=".new", dir=target.parent
            )
            temporary = Path(temporary_name)
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            staged.append((temporary, target))
        for temporary, target in staged:
            os.replace(temporary, target)
        digest = hashlib.sha256()
        for relative in sorted(RELEASE_FILES):
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update((root / relative).read_bytes())
        return {
            "status": "ok",
            "commit": PINNED_COMMIT,
            "files": len(RELEASE_FILES),
            "content_id": digest.hexdigest()[:16],
        }
    finally:
        for temporary, _target in staged:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/app"))
    args = parser.parse_args()
    result = install(args.root)
    print(
        "TEMLI candidate installed: commit={commit}; files={files}; content={content_id}".format(
            **result
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
