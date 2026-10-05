"""Personal bot credentials and connection management."""
import json
import os
import re
import time
import secrets
from telegram_transport import telegram_json, TelegramTransportError

from flask import g, jsonify, request


class ConnectionError(Exception):
    pass


def cipher():
    try:
        from cryptography.fernet import Fernet
        return Fernet(os.environ["TEMLI_BOT_ENCRYPTION_KEY"].encode("ascii"))
    except (ImportError, KeyError, ValueError, UnicodeError):
        raise ConnectionError("unavailable") from None


def telegram_info(token, method, payload=None):
    # Never expose transport exceptions containing token/proxy URLs.
    try:
        result = telegram_json(token, method, payload, timeout=10)
        if not result.get("ok") or not isinstance(result.get("result"), (dict, bool)):
            raise ValueError()
        return result["result"]
    except TelegramTransportError as error:
        if method == 'sendMessage':
            raise ConnectionError(str(error)) from None
        raise ConnectionError('telegram_unavailable') from None
    except Exception:
        raise ConnectionError("telegram_unavailable") from None


def register_routes(host):
    def registry_path():
        return os.path.join(host.BASE_DIR, "personal_bots.json")

    def read():
        records = host._load_json_raw(registry_path(), {})
        if not isinstance(records, dict):
            raise ConnectionError("storage_error")
        return records

    def public(record):
        if not record:
            return None
        return {key: record[key] for key in ("bot_id", "username", "name", "verified_at")}

    def identity():
        teacher = str(getattr(g, "teacher_id", "") or "")
        user = getattr(g, "telegram_user", {}) or {}
        if not teacher or str(user.get("id", "")) != teacher:
            raise ConnectionError("unauthorized")
        return teacher

    def checked(token, current=None):
        if not isinstance(token, str) or not re.fullmatch(r"[0-9]{5,20}:[A-Za-z0-9_-]{20,100}", token):
            raise ConnectionError("invalid_token")
        info = telegram_info(token, "getMe")
        bot_id = str(info.get("id", ""))
        if not info.get("is_bot") or not bot_id.isdigit() or not info.get("username"):
            raise ConnectionError("invalid_token")
        if bot_id == str(host.TOKEN or "").split(":")[0]:
            raise ConnectionError("central_bot")
        webhook_url = telegram_info(token, "getWebhookInfo").get("url")
        own_url = (current or {}).get("webhook", {}).get("url")
        if webhook_url and (webhook_url != own_url or bot_id != (current or {}).get("bot_id")):
            raise ConnectionError("existing_webhook")
        return {"bot_id": bot_id, "username": info["username"],
                "name": info.get("first_name", ""), "verified_at": int(time.time())}

    @host.flask_app.route("/api/personal_bot", methods=["GET", "POST"])
    def personal_bot():
        try:
            teacher = identity()
            try:
                crypt = cipher()
            except ConnectionError:
                if request.method == "GET":
                    return jsonify(status="ok", enabled=False, bot=None)
                raise
            with host.DATA_LOCK:
                records = read()
                current = records.get(teacher)
            if request.method == "GET":
                # Detect a missing/changed master key without returning credentials.
                if current:
                    try:
                        crypt.decrypt(current["token"].encode())
                    except Exception:
                        raise ConnectionError("key_mismatch") from None
                return jsonify(status="ok", enabled=True, bot=public(current))
            data = request.get_json(silent=True) or {}
            if not isinstance(data, dict):
                raise ConnectionError("invalid_request")
            action = data.get("action")
            if action == "preview":
                token = data.get("token", "")
                record = checked(token, current)
                with host.DATA_LOCK:
                    records = read()
                    if any(r.get("bot_id") == record["bot_id"] and owner != teacher
                           for owner, r in records.items()):
                        raise ConnectionError("already_connected")
                ticket = crypt.encrypt(json.dumps({
                    "teacher": teacher, "token": token, "record": record,
                    "previous": current,
                }).encode()).decode()
                return jsonify(status="ok", bot=record, ticket=ticket)
            if action == "connect":
                try:
                    payload = json.loads(crypt.decrypt(str(data.get("ticket", "")).encode(), ttl=300))
                except Exception:
                    raise ConnectionError("expired_preview") from None
                if payload.get("teacher") != teacher:
                    raise ConnectionError("unauthorized")
                record = checked(payload["token"], payload["previous"])
                with host.DATA_LOCK:
                    records = read()
                    current = records.get(teacher)
                    if current != payload["previous"]:
                        raise ConnectionError("changed")
                    if current and current["bot_id"] != record["bot_id"]:
                        raise ConnectionError("disconnect_first")
                    if any(r.get("bot_id") == record["bot_id"] and owner != teacher
                           for owner, r in records.items()):
                        raise ConnectionError("already_connected")
                    records[teacher] = {**(current or {}), **record,
                                       "connection_id": (current or {}).get("connection_id") or secrets.token_urlsafe(24),
                                       "token": crypt.encrypt(payload["token"].encode()).decode()}
                    host._save_json_raw(registry_path(), records)
                return jsonify(status="ok", enabled=True, bot=record)
            if action == "disconnect":
                with host.DATA_LOCK:
                    records = read()
                    current = records.get(teacher)
                    if current and current["bot_id"] != str(data.get("bot_id", "")):
                        raise ConnectionError("changed")
                    if current:
                        # Leave local ownership intact if Telegram cannot confirm removal.
                        if current.get("webhook"):
                            token = crypt.decrypt(current["token"].encode()).decode()
                            remote = telegram_info(token, "getWebhookInfo").get("url")
                            if remote == current["webhook"]["url"]:
                                telegram_info(token, "deleteWebhook", {"drop_pending_updates": False})
                        del records[teacher]
                        host._save_json_raw(registry_path(), records)
                return jsonify(status="ok", enabled=True, bot=None)
            raise ConnectionError("invalid_request")
        except ConnectionError as error:
            code = str(error)
            return jsonify(status="error", code=code), (401 if code == "unauthorized" else 400)
        except Exception:
            # No plaintext credential or provider response in error/log output.
            return jsonify(status="error", code="storage_error"), 503

    from personal_bot_invites import register_invite_routes
    register_invite_routes(host, read, registry_path, identity)
    from personal_notifications import register_routes as register_notifications
    register_notifications(host, read, identity)
