"""Teacher-scoped invitations; personal bot visitors never enter teacher APIs."""
import hashlib
import hmac
import os
import re
import secrets
import time
from urllib.parse import urlsplit

from flask import jsonify, request
import personal_bots as bots
import invitation_channels as channels


def register_invite_routes(host, read_registry, registry_path, identity):
    def links_path():
        return os.path.join(host.tenant_root(), "personal_bot_links.json")

    def read_links():
        value = host._load_json_raw(links_path(), {"invites": {}, "bindings": {}, "updates": {}})
        if not isinstance(value, dict) or any(not isinstance(value.get(k), dict)
                                            for k in ("invites", "bindings", "updates")):
            raise bots.ConnectionError("storage_error")
        return value

    def connection(teacher):
        record = channels.preferred(host, read_registry().get(teacher))
        if not record:
            raise bots.ConnectionError("bot_required")
        return record

    def render_message_template(value, fallback, replacements):
        text = str(value or fallback).strip()
        for key, replacement in replacements.items():
            text = text.replace("{" + key + "}", str(replacement or ""))
        return text

    def sync_active_binding_contacts(students, bindings):
        """Backfill a missing Telegram contact from a teacher-approved binding."""
        changed = False
        for binding in bindings:
            if binding.get("state") != "active":
                continue
            student_id = str(binding.get("student_id", ""))
            if student_id not in students:
                continue
            role = binding.get("role")
            field = "student_contacts" if role == "student" else "contacts" if role == "parent" else ""
            if not field:
                continue
            student = students[student_id]
            if isinstance(student, str):
                student = {"name": student, "user_id": student_id, "contacts": {}, "student_contacts": {}}
                students[student_id] = student
                changed = True
            if not isinstance(student, dict):
                continue
            contacts = student.get(field)
            if not isinstance(contacts, dict):
                contacts = {}
            if str(contacts.get("tg", "") or "").strip():
                continue
            username = str(binding.get("username", "") or "").strip().lstrip("@")
            telegram_id = str(binding.get("telegram_id", "") or "").strip()
            contact = "@" + username if re.fullmatch(r"[A-Za-z0-9_]{1,64}", username) else telegram_id if telegram_id.isdigit() else ""
            if not contact:
                continue
            contacts = dict(contacts)
            contacts["tg"] = contact
            student[field] = contacts
            changed = True
        return changed

    def activate(teacher):
        # Serialization also covers concurrent first-invite activation/disconnect.
        with host.DATA_LOCK:
            records = read_registry()
            record = connection(teacher)
            if record.get('channel') == 'main':
                if not record.get('username'):
                    raise bots.ConnectionError('bot_unavailable')
                return record
            token = bots.cipher().decrypt(record["token"].encode()).decode()
            base = os.getenv("TEMLI_PUBLIC_URL", "https://bot-1787954043-4984-solo1986.bothost.tech").rstrip("/")
            parsed = urlsplit(base)
            if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment or parsed.username or parsed.path:
                raise bots.ConnectionError("public_url")
            webhook = record.get("webhook")
            remote = bots.telegram_info(token, "getWebhookInfo").get("url", "")
            if remote and (not webhook or remote != webhook["url"]):
                raise bots.ConnectionError("existing_webhook")
            if not webhook:
                endpoint = secrets.token_urlsafe(24)
                secret = secrets.token_urlsafe(32)
                webhook = {"endpoint": endpoint, "url": base + "/telegram/personal/" + endpoint,
                           "secret": bots.cipher().encrypt(secret.encode()).decode()}
                record["connection_id"] = record.get("connection_id") or secrets.token_urlsafe(24)
                record["webhook"] = webhook
                records[teacher] = record
                host._save_json_raw(registry_path(), records)
            secret = bots.cipher().decrypt(webhook["secret"].encode()).decode()
            # Reapplying is safe after an interrupted request and refreshes the secret.
            bots.telegram_info(token, "setWebhook", {
                "url": webhook["url"], "secret_token": secret,
                "allowed_updates": ["message"], "drop_pending_updates": False,
            })
            return record

    @host.flask_app.route("/api/personal_invites", methods=["POST"])
    def personal_invites():
        try:
            teacher = identity()
            data = request.get_json(silent=True) or {}
            if not isinstance(data, dict):
                raise bots.ConnectionError("invalid_request")
            student_id = str(data.get("student_id", ""))
            action = data.get("action", "list")
            with host.teacher_scope(teacher), host.DATA_LOCK:
                students = host.load_json(host.STUDENTS_FILE)
                record = read_registry().get(teacher)
                links = read_links()
                available = channels.records(host, record)
                invite_bot = channels.preferred(host, record)
                if action == 'availability':
                    return jsonify(status='ok', bot_username=(invite_bot or {}).get('username'))
                if action == "pending_summary":
                    pending = {}
                    active_bindings = []
                    for binding in links["bindings"].values():
                        sid = str(binding.get("student_id", ""))
                        if not (binding.get("connection_id") in available and sid in students):
                            continue
                        if binding.get("state") == "active":
                            active_bindings.append(binding)
                        elif binding.get("state") == "pending" and binding.get("role") in ("student", "parent"):
                            pending.setdefault(sid, set()).add(binding["role"])
                    contacts_updated = sync_active_binding_contacts(students, active_bindings)
                    if contacts_updated:
                        host.save_json(host.STUDENTS_FILE, students)
                    return jsonify(status="ok", count=sum(len(roles) for roles in pending.values()),
                                   pending=[{"student_id": sid, "roles": sorted(roles)}
                                            for sid, roles in pending.items()],
                                   contacts_updated=contacts_updated)
                if student_id not in students:
                    raise bots.ConnectionError("student_missing")
                if action == "list":
                    bindings = [{**b, "id": key} for key, b in links["bindings"].items()
                                if b["student_id"] == student_id and b["connection_id"] in available and b.get('state') != 'replaced']
                    if sync_active_binding_contacts(students, bindings):
                        host.save_json(host.STUDENTS_FILE, students)
                    return jsonify(status="ok", bot_username=(invite_bot or {}).get("username"),
                                   bindings=bindings, student=students[student_id])
                if action == "create":
                    role = data.get("role")
                    if role not in ("student", "parent"):
                        raise bots.ConnectionError("invalid_request")
                    record = activate(teacher)
                    now = int(time.time())
                    # One current invitation per student/role. Reissue revokes old links.
                    links["invites"] = {k: v for k, v in links["invites"].items()
                                        if v["expires_at"] > now and
                                        not (v["student_id"] == student_id and v["role"] == role)}
                    raw = secrets.token_urlsafe(24)
                    if record.get('channel') == 'main':
                        raw = 'join_' + teacher + '_' + raw
                    digest = hashlib.sha256(raw.encode()).hexdigest()
                    links["invites"][digest] = {"student_id": student_id, "role": role,
                        "connection_id": record["connection_id"], "expires_at": now + 48 * 3600}
                    host._save_json_raw(links_path(), links)
                    return jsonify(status="ok", url=f"https://t.me/{record['username']}?start={raw}",
                                   expires_at=now + 48 * 3600)
                if action not in ("approve", "revoke"):
                    raise bots.ConnectionError("invalid_request")
                key = str(data.get("binding_id", ""))
                binding = links["bindings"].get(key)
                if not binding or binding["student_id"] != student_id or binding["connection_id"] not in available:
                    raise bots.ConnectionError("binding_missing")
                newly_active = action == 'approve' and binding.get('state') != 'active'
                if action == "approve":
                    if binding['role'] == 'student':
                        for other in links['bindings'].values():
                            if other is not binding and other.get('student_id') == student_id and other.get('role') == 'student':
                                other['state'] = 'replaced'
                    binding["state"] = "active"
                    if sync_active_binding_contacts(students, [binding]):
                        host.save_json(host.STUDENTS_FILE, students)
                else:
                    del links["bindings"][key]
                host._save_json_raw(links_path(), links)
                channel = available[binding['connection_id']]
                confirmation = None
                if newly_active and channel.get('channel') == 'main':
                    english = host.load_settings().get('language') == 'en'
                    confirmation = channels.message(host, channel,
                        'Connection confirmed 😊 Lesson updates will arrive here.' if english else
                        'Подключение подтверждено 😊 Теперь сообщения о занятиях будут приходить сюда.')
            # Persist before best-effort sending, without holding the global data lock.
            if confirmation:
                try:
                    bots.telegram_info(channels.token_for(host, channel), 'sendMessage', {
                        'chat_id': binding['chat_id'], 'text': confirmation})
                except bots.ConnectionError:
                    pass
            return jsonify(status="ok", student=students[student_id])
        except bots.ConnectionError as error:
            return jsonify(status="error", code=str(error)), (401 if str(error) == "unauthorized" else 400)
        except Exception:
            return jsonify(status="error", code="storage_error"), 503

    @host.flask_app.route("/telegram/personal/<endpoint>", methods=["POST"])
    def personal_bot_webhook(endpoint):
        # This route is outside /api/: authenticate with Telegram's secret header.
        try:
            if request.content_length and request.content_length > 65536:
                return "", 413
            with host.DATA_LOCK:
                match = [(owner, r) for owner, r in read_registry().items()
                         if r.get("webhook", {}).get("endpoint") == endpoint]
                if len(match) != 1:
                    return "", 404
                teacher, record = match[0]
                expected = bots.cipher().decrypt(record["webhook"]["secret"].encode()).decode()
                supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
                if not hmac.compare_digest(expected, supplied):
                    return "", 403
                update = request.get_json(silent=True)
                if not isinstance(update, dict) or type(update.get("update_id")) is not int:
                    return "", 400
                msg = update.get("message") or {}
                sender, chat = msg.get("from") or {}, msg.get("chat") or {}
                if chat.get("type") != "private" or type(sender.get("id")) is not int or sender["id"] != chat.get("id") or sender.get("is_bot"):
                    return jsonify(ok=True)
                text = msg.get("text", "")
                if not isinstance(text, str) or not text.startswith("/start"):
                    return jsonify(ok=True)
                command = re.fullmatch(r"/start(?:@[A-Za-z0-9_]+)?(?: ([A-Za-z0-9_-]{1,64}))?", text)
                if not command:
                    return jsonify(ok=True)
                raw = command.group(1) or ""
                digest = hashlib.sha256(raw.encode()).hexdigest()
                with host.teacher_scope(teacher):
                    links = read_links()
                    update_key = record["connection_id"] + ":" + str(update["update_id"])
                    if update_key in links["updates"]:
                        return jsonify(ok=True)
                    invite = links["invites"].get(digest)
                    valid = (invite and invite["expires_at"] > time.time()
                             and invite["connection_id"] == record["connection_id"]
                             and invite["student_id"] in host.load_json(host.STUDENTS_FILE))
                    english = str(sender.get("language_code", "")).startswith("en")
                    reply = ("Ask your teacher for a new invitation link." if english
                             else "Попросите преподавателя прислать новую ссылку-приглашение.")
                    if valid:
                        del links["invites"][digest]
                        binding_key = hashlib.sha256(
                            f"{record['connection_id']}:{invite['student_id']}:{invite['role']}:{sender['id']}".encode()).hexdigest()
                        if binding_key not in links["bindings"]:
                            links["bindings"][binding_key] = {
                                "student_id": invite["student_id"], "role": invite["role"],
                                "connection_id": record["connection_id"], "telegram_id": str(sender["id"]),
                                "chat_id": str(chat["id"]), "name": str(sender.get("first_name", ""))[:128],
                                "username": str(sender.get("username", ""))[:64], "state": "pending"}
                        settings = host.load_settings()
                        if invite["role"] == "parent":
                            fallback = ("Hello! Thank you for connecting 😊 I’ll confirm everything soon, and my lesson updates will arrive here." if english
                                        else "Здравствуйте! Спасибо, что подключились 😊 Скоро я всё подтвержу, и сюда будут приходить мои сообщения о занятиях.")
                            template = settings.get("parent_binding_template")
                        else:
                            fallback = ("Hi! We’re connected 😊 I’ll confirm everything soon, and my lesson reminders will arrive here." if english
                                        else "Привет! Мы на связи 😊 Скоро я всё подтвержу, и сюда будут приходить мои напоминания о занятиях.")
                            template = settings.get("student_binding_template")
                        reply = render_message_template(template, fallback, {
                            "name": str(sender.get("first_name", "") or "")[:128]
                        })
                    links["updates"][update_key] = int(time.time())
                    links["updates"] = dict(list(links["updates"].items())[-2000:])
                    host._save_json_raw(links_path(), links)
                token = bots.cipher().decrypt(record["token"].encode()).decode()
            # Best-effort acknowledgement; retries must never create a second binding.
            try:
                bots.telegram_info(token, "sendMessage", {"chat_id": chat["id"], "text": reply})
            except bots.ConnectionError:
                pass
            return jsonify(ok=True)
        except Exception:
            # Telegram retries persistence failures. Never log credential-bearing errors.
            return "", 503
