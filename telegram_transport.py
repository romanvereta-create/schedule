"""Explicit, Telegram-only proxy configuration. Never install a global proxy."""
import os
import re
from urllib.parse import urlsplit

import httpx


class TelegramTransportError(RuntimeError):
    """Only fixed error codes may escape this transport."""


def telegram_proxy_url():
    value = os.environ.get("TELEGRAM_PROXY_URL", "").strip()
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme in {"http", "https", "socks5", "socks5h"}
                 and parsed.hostname and parsed.port and parsed.path in {"", "/"}
                 and not parsed.query and not parsed.fragment
                 and not any(c.isspace() or ord(c) < 32 for c in value))
    except ValueError:
        valid = False
    if not valid:
        raise TelegramTransportError("invalid_TELEGRAM_PROXY_URL") from None
    return value


def validate_proxy_environment():
    # Global proxy variables could route urllib storage/backup traffic abroad.
    if any(value for key, value in os.environ.items()
           if key.lower() in {"http_proxy", "https_proxy", "all_proxy"}):
        raise TelegramTransportError("remove_global_proxy_variables_use_TELEGRAM_PROXY_URL")
    return telegram_proxy_url()


def check_telegram_target(url, proxy, request_data=None):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != "api.telegram.org"
            or parsed.port not in (None, 443) or parsed.username or parsed.password
            or parsed.query or parsed.fragment
            or not re.fullmatch(r"/bot[^/]+/[A-Za-z][A-Za-z0-9]*", parsed.path)):
        raise TelegramTransportError("telegram_target_not_allowed")
    method = parsed.path.rsplit("/", 1)[-1].lower()
    if proxy and (method in {
        "senddocument", "sendphoto", "sendvideo", "sendanimation", "sendaudio",
        "sendvoice", "sendvideonote", "sendmediagroup", "sendsticker", "getfile",
        "uploadstickerfile", "setchatphoto", "editmessagemedia",
    } or (request_data is not None and request_data.multipart_data)):
        raise TelegramTransportError("telegram_files_disabled_with_proxy")


def telegram_json(token, method, payload=None, *, timeout=10):
    """Sync Bot API transport for personal bots and operational alerts."""
    proxy = telegram_proxy_url()
    url = f"https://api.telegram.org/bot{token}/{method}"
    check_telegram_target(url, proxy)
    try:
        with httpx.Client(proxy=proxy, trust_env=False, follow_redirects=False,
                          timeout=timeout) as client:
            response = client.post(url, json=payload or {})
            if response.status_code != 200:
                code = {403: "recipient_blocked", 400: "recipient_unavailable",
                        401: "bot_invalid", 429: "rate_limited"}.get(
                            response.status_code, "telegram_unavailable")
                raise TelegramTransportError(code)
            result = response.json()
            if not isinstance(result, dict) or result.get("ok") is not True:
                raise TelegramTransportError("telegram_unavailable")
            return result
    except TelegramTransportError:
        raise
    except Exception:
        raise TelegramTransportError("telegram_unavailable") from None
