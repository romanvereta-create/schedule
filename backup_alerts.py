"""Owner-only backup incident notifications; no student data or exception text."""
import json
import re
import threading
import time
from pathlib import Path
from telegram_transport import telegram_json

_LOCK = threading.Lock()
_MEMORY = {}
REPEAT_SECONDS = 86400
RETRY_SECONDS = 3600


def configured(host):
    return bool(getattr(host, "TOKEN", "") and
                re.fullmatch(r"[1-9][0-9]*", str(getattr(host, "OWNER_ID", ""))))


def send_owner(host, text):
    if not configured(host):
        return False
    try:
        return telegram_json(host.TOKEN, "sendMessage",
                             {"chat_id": str(host.OWNER_ID), "text": text},
                             timeout=15).get("ok") is True
    except Exception:
        # Provider errors may contain the token URL. Never log them.
        return False


def notify(host, output, outcome, now=None):
    """Persist attempt before sending. Disk failure retains in-process throttling."""
    if not configured(host) or outcome == "busy":
        return
    from automatic_backup import atomic_write, read_json
    now = time.time() if now is None else now
    path = Path(output) / "owner-alert.json"
    with _LOCK:
        state = _MEMORY.get(str(path)) or read_json(path)
        def save():
            _MEMORY[str(path)] = dict(state)
            try:
                atomic_write(path, json.dumps(state).encode())
            except OSError:
                pass
        failure = outcome in ("failed", "warning")
        if failure:
            if state.get("phase") != "incident":
                state = {"phase": "incident", "notified": False}
            elif outcome == "failed" and state.get("outcome") == "warning":
                state.pop("attempt_at", None)
            interval = REPEAT_SECONDS if state.get("notified") else RETRY_SECONDS
            if now - state.get("attempt_at", -REPEAT_SECONDS) < interval:
                save()
                return
            text = ("TEMLI: резервная копия создана, но не удалось очистить старые архивы. "
                    "Проверь python /app/automatic_backup.py status."
                    if outcome == "warning" else
                    "TEMLI: не удалось создать или загрузить резервную копию. "
                    "Я повторю попытку через 15 минут. "
                    "Проверь python /app/automatic_backup.py status.")
            state["outcome"] = outcome
        else:
            if state.get("phase") == "incident":
                # already_done only proves an older copy exists, not that the failed attempt recovered.
                if outcome != "ok":
                    return
                if not state.get("notified"):
                    state = {"phase": "healthy"}
                    save()
                    return
                state = {"phase": "recovery"}
            if state.get("phase") != "recovery":
                return
            if now - state.get("attempt_at", -RETRY_SECONDS) < RETRY_SECONDS:
                return
            text = "TEMLI: резервное копирование снова работает. Свежая копия сохранена на Google Диске."
        state["attempt_at"] = now
        save()
        if send_owner(host, text):
            if failure:
                state["notified"] = True
            else:
                state = {"phase": "healthy"}
        save()
