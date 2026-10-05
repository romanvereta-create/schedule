#!/usr/bin/env python3
"""Create least-privilege deployment env files without printing secrets."""

from __future__ import annotations

import base64
import os
import re
import secrets
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent
PUBLIC_HOST = "temli.135-106-173-105.sslip.io"
MIGRATION_KEYS = {
    "SCHEDULE_BOT_TOKEN",
    "SCHEDULE_OWNER_ID",
    "TELEGRAM_PROXY_URL",
}


def read_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise SystemExit(f"Invalid line {number} in {path.name}")
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or "\n" in value or "\r" in value:
            raise SystemExit(f"Invalid entry on line {number} in {path.name}")
        result[key] = value.strip()
    return result


def validate(values: dict[str, str]) -> None:
    if set(values) != MIGRATION_KEYS:
        raise SystemExit("migration.env must contain exactly the documented three variables")
    if not re.fullmatch(r"[1-9][0-9]{4,14}:[A-Za-z0-9_-]{20,}", values["SCHEDULE_BOT_TOKEN"]):
        raise SystemExit("SCHEDULE_BOT_TOKEN has an invalid format")
    if not re.fullmatch(r"[1-9][0-9]*", values["SCHEDULE_OWNER_ID"]):
        raise SystemExit("SCHEDULE_OWNER_ID must be a positive Telegram numeric id")
    try:
        proxy = urlsplit(values["TELEGRAM_PROXY_URL"])
        valid_proxy = (
            proxy.scheme in {"http", "https", "socks5", "socks5h"}
            and bool(proxy.hostname)
            and bool(proxy.port)
            and proxy.path in {"", "/"}
            and not proxy.query
            and not proxy.fragment
        )
    except ValueError:
        valid_proxy = False
    if not valid_proxy:
        raise SystemExit("TELEGRAM_PROXY_URL has an invalid format")


def random_token() -> str:
    return secrets.token_urlsafe(48)


def fernet_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")


def write_private(path: Path, values: dict[str, str]) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as target:
            for key, value in values.items():
                target.write(f"{key}={value}\n")
            target.flush()
            os.fsync(target.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def main() -> None:
    migration_path = ROOT / "migration.env"
    if not migration_path.is_file():
        raise SystemExit("Copy the locally completed migration.env to this directory first")
    migration = read_env(migration_path)
    validate(migration)

    outputs = (ROOT / "app.env", ROOT / "shared.env", ROOT / "storage.env")
    if any(path.exists() for path in outputs):
        raise SystemExit("Refusing to overwrite existing deployment secrets")

    write_private(ROOT / "shared.env", {
        "TEMLI_STORAGE_APP_TOKEN": random_token(),
        "TEMLI_STORAGE_BACKUP_READ_TOKEN": random_token(),
    })
    write_private(ROOT / "storage.env", {
        "TEMLI_STORAGE_ADMIN_TOKEN": random_token(),
        "TEMLI_BACKUP_ENCRYPTION_KEY": fernet_key(),
    })
    write_private(ROOT / "app.env", {
        **migration,
        "SCHEDULE_BOT_USERNAME": "TEMLI_bot",
        "SCHEDULE_TIMEZONE": "Europe/Moscow",
        "SCHEDULE_WEBAPP_URL": f"https://{PUBLIC_HOST}/app/",
        "SCHEDULE_WEBAPP_ORIGIN": f"https://{PUBLIC_HOST}",
        "TEMLI_PUBLIC_URL": f"https://{PUBLIC_HOST}",
        "TEMLI_DEPLOYMENT_ID": "temli-selectel-candidate",
        "TEMLI_BOT_ENCRYPTION_KEY": fernet_key(),
        "TEMLI_CONSENT_LEDGER_HMAC_KEY": random_token(),
        "TEMLI_DSR_HASH_KEY": random_token(),
        "TEMLI_CONSENT_ENFORCEMENT": "false",
        "TEMLI_REPLICA_INTERVAL_SECONDS": "21600",
        "TEMLI_REPLICA_RETENTION": "60",
    })
    (ROOT / ".env").write_text(
        f"TEMLI_PUBLIC_HOST={PUBLIC_HOST}\n", encoding="utf-8", newline="\n"
    )
    os.chmod(ROOT / ".env", 0o600)
    migration_path.unlink()
    print("Deployment secrets initialized; migration.env removed from the server.")


if __name__ == "__main__":
    main()
