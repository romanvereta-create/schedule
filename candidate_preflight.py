"""Fail-closed, secret-safe preflight for a TEMLI production candidate.

The command performs local configuration checks only.  It deliberately does
not contact Telegram or storage and never includes environment values in its
report, making the JSON output safe for build logs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit


REQUIRED_ENV = (
    "TEMLI_DEPLOYMENT_ID",
    "SCHEDULE_BOT_TOKEN",
    "SCHEDULE_BOT_USERNAME",
    "SCHEDULE_OWNER_ID",
    "SCHEDULE_TIMEZONE",
    "SCHEDULE_WEBAPP_URL",
    "SCHEDULE_WEBAPP_ORIGIN",
    "TEMLI_STORAGE_URL",
    "TEMLI_STORAGE_TOKEN",
    "TEMLI_REPLICA_DIR",
    "ALLOW_UNAUTHENTICATED",
)

# These identify the existing live bot, which must never be selected by a
# candidate deployment.  Comparisons are case-insensitive.
FORBIDDEN_HOSTS = {
    "bot-1787954043-4984-solo1986.bothost.tech",
}
FORBIDDEN_BOT_USERNAMES = {
    "schedule_vereta_bot",
}
FORBIDDEN_DEPLOYMENT_IDS = {
    "production",
    "temli-prod",
    "temli_prod",
}

TOKEN_RE = re.compile(r"^[1-9][0-9]{4,14}:[A-Za-z0-9_-]{20,}$")
USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,30}bot$", re.IGNORECASE)
DEPLOYMENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")


@dataclass(frozen=True)
class Result:
    name: str
    ok: bool
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": "ok" if self.ok else "error",
            "message": self.message,
        }


def _ok(name: str, message: str) -> Result:
    return Result(name, True, message)


def _error(name: str, message: str) -> Result:
    return Result(name, False, message)


def _https_url(value: str, *, require_root: bool = False):
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        return None
    if require_root and parsed.path not in ("", "/"):
        return None
    return parsed


def check_docker_contract(root: Path) -> list[Result]:
    name = "docker_python_contract"
    dockerfile = root / "Dockerfile"
    try:
        text = dockerfile.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return [_error(name, "Dockerfile is missing or unreadable")]

    instructions = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not instructions or not re.match(
        r"(?i)^FROM\s+python:3\.11(?:[.-]|$)", instructions[0]
    ):
        return [_error(name, "Dockerfile must start from Python 3.11")]

    runtime = [
        line for line in instructions if re.match(r"(?i)^(CMD|ENTRYPOINT)\s+", line)
    ]
    if len(runtime) != 1:
        return [_error(name, "Dockerfile must define exactly one runtime command")]
    keyword, raw_command = runtime[0].split(None, 1)
    try:
        command = json.loads(raw_command)
    except json.JSONDecodeError:
        return [_error(name, "Docker runtime command must use JSON form")]
    if keyword.upper() != "CMD" or command != ["python", "-u", "bot.py"]:
        return [_error(name, "Docker runtime command must start bot.py with Python")]

    executable = "\n".join(
        line for line in instructions if re.match(r"(?i)^(RUN|CMD|ENTRYPOINT)\s+", line)
    )
    if re.search(
        r"(?i)(?:^|[^a-z0-9_.-])(node|npm|npx|yarn|pnpm|bun)(?:$|[^a-z0-9_.-])",
        executable,
    ):
        return [_error(name, "Node runtime commands are forbidden")]
    return [_ok(name, "Python 3.11 runtime contract is valid")]


def check_environment(environ: Mapping[str, str]) -> list[Result]:
    results: list[Result] = []
    missing = [name for name in REQUIRED_ENV if not str(environ.get(name, "")).strip()]
    if missing:
        results.append(
            _error("required_environment", "missing variables: " + ", ".join(missing))
        )
    else:
        results.append(_ok("required_environment", "all required variables are set"))

    deployment_id = str(environ.get("TEMLI_DEPLOYMENT_ID", "")).strip().lower()
    if (
        not DEPLOYMENT_ID_RE.fullmatch(deployment_id)
        or "candidate" not in deployment_id
        or deployment_id in FORBIDDEN_DEPLOYMENT_IDS
    ):
        results.append(
            _error(
                "candidate_identity",
                "TEMLI_DEPLOYMENT_ID must be an explicit candidate identifier",
            )
        )
    else:
        results.append(_ok("candidate_identity", "candidate deployment identity is explicit"))

    token = str(environ.get("SCHEDULE_BOT_TOKEN", "")).strip()
    if not TOKEN_RE.fullmatch(token):
        results.append(_error("bot_token_format", "SCHEDULE_BOT_TOKEN format is invalid"))
    else:
        results.append(_ok("bot_token_format", "bot token format is valid"))

    username = str(environ.get("SCHEDULE_BOT_USERNAME", "")).strip().lstrip("@").lower()
    if not USERNAME_RE.fullmatch(username):
        results.append(_error("candidate_bot_identity", "bot username format is invalid"))
    elif username in FORBIDDEN_BOT_USERNAMES:
        results.append(
            _error("candidate_bot_identity", "known production bot username is forbidden")
        )
    else:
        results.append(_ok("candidate_bot_identity", "candidate bot identity is separate"))

    owner_id = str(environ.get("SCHEDULE_OWNER_ID", "")).strip()
    if not re.fullmatch(r"[1-9][0-9]*", owner_id):
        results.append(_error("owner_identity", "SCHEDULE_OWNER_ID must be a positive integer"))
    else:
        results.append(_ok("owner_identity", "owner identity format is valid"))

    if str(environ.get("SCHEDULE_TIMEZONE", "")).strip() != "Europe/Moscow":
        results.append(_error("timezone", "candidate timezone must be Europe/Moscow"))
    else:
        results.append(_ok("timezone", "candidate timezone is explicit"))

    storage = _https_url(str(environ.get("TEMLI_STORAGE_URL", "")), require_root=True)
    if storage is None:
        results.append(_error("storage_url", "TEMLI_STORAGE_URL must be a clean HTTPS base URL"))
    elif storage.hostname.lower() in FORBIDDEN_HOSTS:
        results.append(_error("storage_url", "known production host is forbidden"))
    else:
        results.append(_ok("storage_url", "storage uses a non-production HTTPS host"))

    storage_token = str(environ.get("TEMLI_STORAGE_TOKEN", ""))
    if len(storage_token) < 32 or storage_token.strip() != storage_token:
        results.append(
            _error("storage_token_format", "TEMLI_STORAGE_TOKEN format is invalid")
        )
    else:
        results.append(_ok("storage_token_format", "storage token format is valid"))

    replica_dir = str(environ.get("TEMLI_REPLICA_DIR", "")).strip()
    if not replica_dir.startswith("/app/data/") or ".." in replica_dir.split("/"):
        results.append(_error(
            "replica_directory",
            "TEMLI_REPLICA_DIR must be inside the persistent /app/data directory",
        ))
    else:
        results.append(_ok("replica_directory", "offsite replica directory is persistent"))

    webapp = _https_url(str(environ.get("SCHEDULE_WEBAPP_URL", "")))
    if webapp is None or webapp.path != "/app/":
        results.append(
            _error("webapp_url", "SCHEDULE_WEBAPP_URL must be a self-hosted HTTPS /app/ URL")
        )
    elif webapp.hostname.lower() in FORBIDDEN_HOSTS or webapp.hostname.lower().endswith("github.io"):
        results.append(_error("webapp_url", "shared or known production frontend is forbidden"))
    else:
        results.append(_ok("webapp_url", "candidate WebApp is self-hosted at /app/"))

    origin = _https_url(str(environ.get("SCHEDULE_WEBAPP_ORIGIN", "")), require_root=True)
    if origin is None:
        results.append(_error("webapp_origin", "SCHEDULE_WEBAPP_ORIGIN must be a clean HTTPS origin"))
    elif webapp is None or (origin.scheme, origin.netloc) != (webapp.scheme, webapp.netloc):
        results.append(_error("webapp_origin", "WebApp URL and origin must use the same host"))
    else:
        results.append(_ok("webapp_origin", "WebApp origin matches its self-hosted URL"))

    if str(environ.get("ALLOW_UNAUTHENTICATED", "")).strip().lower() != "false":
        results.append(_error("authentication", "ALLOW_UNAUTHENTICATED must be explicitly false"))
    else:
        results.append(_ok("authentication", "Telegram authentication is enforced"))

    return results


def run_preflight(root: Path, environ: Mapping[str, str]) -> dict[str, object]:
    results = check_docker_contract(root) + check_environment(environ)
    return {
        "status": "ok" if all(item.ok for item in results) else "error",
        "checks": [item.as_dict() for item in results],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate TEMLI production-candidate configuration")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_preflight(args.root.resolve(), os.environ)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
