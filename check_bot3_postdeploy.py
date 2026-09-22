"""Public, secret-free post-deploy smoke check for TEMLI Bot3.

The check intentionally uses only public health endpoints.  It never accepts an
authorization token and never includes response bodies or endpoint URLs in its
output, so it is safe to use in CI logs.
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


DEFAULT_BOT_BASE_URL = "https://bot-1789984567-3598-solo1986.bothost.tech"
DEFAULT_STORAGE_BASE_URL = "https://bot-1789853066-7755-solo1986.bothost.tech"
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_ATTEMPTS = 2
MAX_BACKUP_AGE_SECONDS = 8 * 60 * 60

BOT_CAPABILITIES = {
    "request-json-cache-v1",
    "bootstrap-v1",
    "self-hosted-frontend-v1",
    "readiness-v1",
    "release-id-v1",
}
STORAGE_CAPABILITIES = {
    "json",
    "files-v1",
    "backup-v2",
    "authenticated-status-v1",
    "backup-integrity-status-v1",
}


class CheckError(RuntimeError):
    """Expected smoke-check failure with a log-safe message."""


@dataclass(frozen=True)
class EndpointCheck:
    name: str
    url: str
    validate: Callable[[dict[str, Any]], dict[str, Any]]


def _public_endpoint(base_url: str, path: str, *, allow_http: bool = False) -> str:
    """Build an endpoint while rejecting URL features that commonly carry secrets."""
    parsed = urlsplit(base_url.strip())
    allowed_schemes = {"https", "http"} if allow_http else {"https"}
    if parsed.scheme not in allowed_schemes:
        raise ValueError("endpoint must use HTTPS")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("endpoint must have a host and no embedded credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("endpoint must not contain a query or fragment")
    clean_base_path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, clean_base_path + path, "", ""))


def _require_equal(payload: dict[str, Any], key: str, expected: Any) -> None:
    if payload.get(key) != expected:
        raise CheckError(f"field {key!r} must equal {expected!r}")


def _require_capabilities(payload: dict[str, Any], required: set[str]) -> list[str]:
    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, list) or not all(
        isinstance(item, str) for item in capabilities
    ):
        raise CheckError("field 'capabilities' must be a list of strings")
    missing = sorted(required.difference(capabilities))
    if missing:
        raise CheckError("missing capabilities: " + ", ".join(missing))
    return sorted(required)


def validate_bot_health(payload: dict[str, Any]) -> dict[str, Any]:
    _require_equal(payload, "status", "ok")
    _require_equal(payload, "storage", "remote-json-test")
    capabilities = _require_capabilities(payload, BOT_CAPABILITIES)
    release = payload.get("release")
    if not isinstance(release, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", release):
        raise CheckError("field 'release' must be a public release identifier")
    return {
        "status": "ok",
        "storage": "remote-json-test",
        "release": release,
        "capabilities": capabilities,
    }


def validate_bot_ready(payload: dict[str, Any]) -> dict[str, Any]:
    _require_equal(payload, "status", "ok")
    _require_equal(payload, "service", "temli-bot3")
    _require_equal(payload, "storage", "ok")

    backup_count = payload.get("backup_count")
    if isinstance(backup_count, bool) or not isinstance(backup_count, int) or backup_count <= 0:
        raise CheckError("field 'backup_count' must be a positive integer")

    latency = payload.get("storage_latency_ms")
    if isinstance(latency, bool) or not isinstance(latency, (int, float)) or latency < 0:
        raise CheckError("field 'storage_latency_ms' must be a non-negative number")

    backup_age = payload.get("latest_backup_age_seconds")
    if (
        isinstance(backup_age, bool)
        or not isinstance(backup_age, int)
        or not 0 <= backup_age <= MAX_BACKUP_AGE_SECONDS
    ):
        raise CheckError("latest backup is missing or older than 8 hours")
    if payload.get("latest_backup_verified") is not True:
        raise CheckError("latest backup is not verified")

    return {
        "status": "ok",
        "storage": "ok",
        "backup_count": backup_count,
        "latest_backup_age_seconds": backup_age,
        "latest_backup_verified": True,
        "storage_latency_ms": latency,
    }


def validate_storage_health(payload: dict[str, Any]) -> dict[str, Any]:
    _require_equal(payload, "status", "ok")
    _require_equal(payload, "service", "temli-storage")
    capabilities = _require_capabilities(payload, STORAGE_CAPABILITIES)
    return {"status": "ok", "service": "temli-storage", "capabilities": capabilities}


def fetch_json(
    url: str,
    timeout: float,
    *,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    request = Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "temli-bot3-smoke/1"},
        method="GET",
    )
    try:
        with opener(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                raise CheckError(f"unexpected HTTP status {status}")
            raw = response.read()
    except HTTPError as exc:
        raise CheckError(f"unexpected HTTP status {exc.code}") from None
    except (URLError, TimeoutError, socket.timeout):
        raise CheckError("network request failed or timed out") from None
    except OSError:
        raise CheckError("network request failed") from None

    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise CheckError("response is not valid JSON") from None
    if not isinstance(payload, dict):
        raise CheckError("JSON response must be an object")
    return payload


def run_endpoint_check(
    check: EndpointCheck,
    *,
    timeout: float,
    attempts: int,
    fetcher: Callable[[str, float], dict[str, Any]] = fetch_json,
) -> dict[str, Any]:
    last_error = "check failed"
    for attempt in range(1, attempts + 1):
        try:
            details = check.validate(fetcher(check.url, timeout))
            return {"status": "ok", "attempt": attempt, "details": details}
        except CheckError as exc:
            last_error = str(exc)
            if attempt < attempts:
                time.sleep(0.25)
    return {"status": "error", "attempt": attempts, "error": last_error}


def run_checks(
    bot_base_url: str,
    storage_base_url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    attempts: int = DEFAULT_ATTEMPTS,
    allow_http: bool = False,
    fetcher: Callable[[str, float], dict[str, Any]] = fetch_json,
) -> dict[str, Any]:
    if not 0.5 <= timeout <= 60:
        raise ValueError("timeout must be between 0.5 and 60 seconds")
    if not 1 <= attempts <= 5:
        raise ValueError("attempts must be between 1 and 5")

    checks = [
        EndpointCheck(
            "bot_health",
            _public_endpoint(bot_base_url, "/api/health", allow_http=allow_http),
            validate_bot_health,
        ),
        EndpointCheck(
            "bot_ready",
            _public_endpoint(bot_base_url, "/api/ready", allow_http=allow_http),
            validate_bot_ready,
        ),
        EndpointCheck(
            "storage_health",
            _public_endpoint(storage_base_url, "/health", allow_http=allow_http),
            validate_storage_health,
        ),
    ]

    results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=len(checks)) as executor:
        futures = {
            executor.submit(
                run_endpoint_check,
                check,
                timeout=timeout,
                attempts=attempts,
                fetcher=fetcher,
            ): check.name
            for check in checks
        }
        for future in as_completed(futures):
            results[futures[future]] = future.result()

    ordered = {check.name: results[check.name] for check in checks}
    return {
        "status": "ok" if all(item["status"] == "ok" for item in ordered.values()) else "error",
        "checks": ordered,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check Bot3 and its remote storage")
    parser.add_argument("--bot-base-url", default=DEFAULT_BOT_BASE_URL)
    parser.add_argument("--storage-base-url", default=DEFAULT_STORAGE_BASE_URL)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--attempts", type=int, default=DEFAULT_ATTEMPTS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run_checks(
            args.bot_base_url,
            args.storage_base_url,
            timeout=args.timeout,
            attempts=args.attempts,
        )
    except ValueError as exc:
        report = {"status": "error", "error": str(exc)}
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
