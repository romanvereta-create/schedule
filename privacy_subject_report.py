"""Read-only, PII-minimised inventory for TEMLI data-subject requests."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any


MAX_JSON_BYTES = 32 * 1024 * 1024
SAFE_ID = re.compile(r"[0-9]{1,20}")

ROOT_FILES = {
    "teacher_registry.json": "teacher_registry",
    "personal_bots.json": "personal_bot_metadata",
    "main_invite_visitors.json": "main_invite_visitors",
}
TENANT_FILES = {
    "students.json": "students",
    "schedule.json": "schedules",
    "payments.json": "payments",
    "personal_bot_links.json": "invites_and_bindings",
    "personal_notification_log.json": "notification_logs",
    "settings.json": "tenant_settings",
}


class UnsafeStorage(ValueError):
    """Storage cannot be inspected without crossing a safety boundary."""


def _checked_root(value: str) -> Path:
    root = Path(value).absolute()
    if not root.exists() or not root.is_dir():
        raise UnsafeStorage("storage root is not an existing directory")
    current = root
    while True:
        if current.is_symlink():
            raise UnsafeStorage("storage root contains a symlink component")
        if current.parent == current:
            break
        current = current.parent
    return root.resolve(strict=True)


def _checked_file(root: Path, relative: Path) -> Path | None:
    if relative.is_absolute() or ".." in relative.parts:
        raise UnsafeStorage("unsafe relative path")
    candidate = root.joinpath(relative)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise UnsafeStorage(f"symlink refused: {relative.as_posix()}")
    if not candidate.exists():
        return None
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError:
        raise UnsafeStorage("path escapes storage root") from None
    mode = resolved.stat().st_mode
    if not stat.S_ISREG(mode):
        raise UnsafeStorage(f"non-regular file refused: {relative.as_posix()}")
    if resolved.stat().st_size > MAX_JSON_BYTES:
        raise UnsafeStorage(f"JSON file exceeds safety limit: {relative.as_posix()}")
    return resolved


def _load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as source:
            return json.load(source)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise UnsafeStorage(f"unreadable JSON: {path.name}") from exc


def _equal_id(value: Any, subject_id: str) -> bool:
    return (isinstance(value, (str, int)) and not isinstance(value, bool)
            and str(value) == subject_id)


def _matching_records(value: Any, subject_id: str) -> int:
    """Count nearest JSON records containing the ID, without returning content."""
    if isinstance(value, dict):
        count = 0
        for key, child in value.items():
            if str(key) == subject_id:
                count += 1
            elif isinstance(child, (dict, list)):
                nested = _matching_records(child, subject_id)
                count += nested
            elif _equal_id(child, subject_id):
                count += 1
        return count
    if isinstance(value, list):
        return sum(1 if _equal_id(item, subject_id)
                   else _matching_records(item, subject_id)
                   for item in value)
    return int(_equal_id(value, subject_id))


def _top_level_records(value: Any) -> int:
    if isinstance(value, (dict, list)):
        return len(value)
    return int(value is not None)


def _subject_hash(kind: str, subject_id: str, key: str) -> str:
    return hmac.new(key.encode("utf-8"), f"{kind}:{subject_id}".encode("ascii"),
                    hashlib.sha256).hexdigest()[:24]


def build_report(root_value: str, kind: str, subject_id: str, hash_key: str) -> dict[str, Any]:
    if kind not in {"telegram", "teacher"}:
        raise ValueError("subject kind must be telegram or teacher")
    if not SAFE_ID.fullmatch(subject_id):
        raise ValueError("subject identifier must contain 1-20 decimal digits")
    if len(hash_key.encode("utf-8")) < 32:
        raise ValueError("hash key must contain at least 32 bytes")
    root = _checked_root(root_value)
    matches: list[dict[str, Any]] = []

    def inspect(relative: Path, category: str, all_records: bool = False,
                report_path: str | None = None) -> None:
        path = _checked_file(root, relative)
        if path is None:
            return
        value = _load_json(path)
        count = _top_level_records(value) if all_records else _matching_records(value, subject_id)
        if count:
            matches.append({"path": report_path or relative.as_posix(), "category": category,
                            "record_count": count})

    for name, category in ROOT_FILES.items():
        inspect(Path(name), category)

    tenants = root / "teacher_data"
    if tenants.exists():
        if tenants.is_symlink() or not tenants.is_dir():
            raise UnsafeStorage("teacher_data must be a real directory")
        for entry in sorted(tenants.iterdir(), key=lambda item: item.name):
            if entry.is_symlink():
                raise UnsafeStorage("symlink refused below teacher_data")
            if not entry.is_dir() or not SAFE_ID.fullmatch(entry.name):
                continue
            if kind == "teacher" and entry.name != subject_id:
                continue
            tenant_label = "tenant-" + _subject_hash("tenant", entry.name, hash_key)[:12]
            for name, category in TENANT_FILES.items():
                inspect(Path("teacher_data") / entry.name / name, category,
                        all_records=(kind == "teacher" and entry.name == subject_id),
                        report_path=f"teacher_data/{tenant_label}/{name}")

    # Legacy single-tenant files remain part of the inventory.
    for name, category in TENANT_FILES.items():
        inspect(Path(name), category)

    matches.sort(key=lambda item: (item["path"], item["category"]))
    return {
        "schema": "temli-privacy-subject-report-v1",
        "mode": "read_only",
        "subject": {"kind": kind, "stable_hash": _subject_hash(kind, subject_id, hash_key)},
        "summary": {"files_with_matches": len(matches),
                    "record_count": sum(item["record_count"] for item in matches)},
        "matches": matches,
        "deletion_plan": {
            "automatic_deletion": False,
            "reason": "cross-file retention and referential-integrity review required",
            "review_categories": sorted({item["category"] for item in matches}),
            "backup_action": "record suppression marker and apply approved retention cycle",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-root", required=True)
    subject = parser.add_mutually_exclusive_group(required=True)
    subject.add_argument("--telegram-id")
    subject.add_argument("--teacher-id")
    parser.add_argument("--hash-key-env", default="TEMLI_DSR_HASH_KEY",
                        help="environment variable containing a private HMAC key")
    args = parser.parse_args(argv)
    subject_id = args.telegram_id or args.teacher_id
    kind = "telegram" if args.telegram_id else "teacher"
    try:
        key = os.environ.get(args.hash_key_env, "")
        report = build_report(args.storage_root, kind, subject_id, key)
    except (ValueError, UnsafeStorage) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
