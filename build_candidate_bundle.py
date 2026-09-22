"""Build a deterministic, secret-safe TEMLI production-candidate bundle.

The bundle is intentionally based on an explicit allowlist.  Repository
metadata, tests, persistent data and local configuration therefore cannot be
included by a broad directory copy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath


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

MANIFEST_NAME = "RELEASE_MANIFEST.json"
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
SECRET_PATTERNS = (
    ("Telegram bot token", re.compile(rb"(?<![0-9])[1-9][0-9]{4,14}:[A-Za-z0-9_-]{20,}")),
    ("private key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("Google client secret", re.compile(rb'"client_secret"\s*:\s*"[^"\r\n]+"')),
)


class BuildError(RuntimeError):
    """The release input is incomplete or unsafe."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_release_files(source: Path) -> dict[str, bytes]:
    payload: dict[str, bytes] = {}
    for relative in RELEASE_FILES:
        path = source.joinpath(*PurePosixPath(relative).parts)
        if not path.is_file():
            raise BuildError(f"required release file is missing: {relative}")
        data = path.read_bytes()
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(data):
                raise BuildError(f"possible {label} in release file: {relative}")
        payload[relative] = data
    return payload


def _release_id(payload: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(payload):
        data = payload[relative]
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(len(data)).encode("ascii"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(_sha256(data)))
    return f"temli-pc-{digest.hexdigest()[:20]}"


def _manifest(payload: dict[str, bytes]) -> bytes:
    document = {
        "artifact": "temli-production-candidate",
        "files": [
            {
                "path": relative,
                "sha256": _sha256(payload[relative]),
                "size": len(payload[relative]),
            }
            for relative in sorted(payload)
        ],
        "release_id": _release_id(payload),
        "schema": 1,
    }
    return (json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def build_bundle(source: Path, output: Path) -> dict[str, object]:
    """Build *output* and return a secret-free machine-readable summary."""
    source = source.resolve()
    output = output.resolve()
    payload = _read_release_files(source)
    manifest = _manifest(payload)
    manifest_document = json.loads(manifest)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            for relative in sorted(payload):
                archive.writestr(_zip_info(relative), payload[relative], compresslevel=9)
            archive.writestr(_zip_info(MANIFEST_NAME), manifest, compresslevel=9)
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()

    bundle_sha256 = _sha256(output.read_bytes())
    checksum = output.with_name(output.name + ".sha256")
    checksum.write_text(f"{bundle_sha256}  {output.name}\n", encoding="ascii", newline="\n")
    return {
        "bundle": str(output),
        "bundle_sha256": bundle_sha256,
        "file_count": len(payload),
        "manifest_sha256": _sha256(manifest),
        "release_id": manifest_document["release_id"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build deterministic TEMLI candidate bundle")
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent / "dist" / "temli-production-candidate.zip",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = build_bundle(args.source, args.output)
    except (BuildError, OSError, zipfile.BadZipFile) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "ok", **report}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
