"""Resolve the bot that a recipient actually joined; never silently migrate bindings."""
import hashlib
import os
import re
import time
import personal_bots as bots


def main_record(host):
    token = str(host.TOKEN or '')
    if not token:
        return None
    username = os.getenv('SCHEDULE_BOT_USERNAME', '').lstrip('@')
    application = getattr(host, 'BOT_APPLICATION', None)
    if application:
        try:
            username = application.bot.username or username
        except RuntimeError:
            pass
    return {'channel': 'main', 'username': username,
            'connection_id': 'main:' + token.split(':', 1)[0]}


def records(host, personal):
    result = {}
    for record in (personal, main_record(host)):
        if record and record.get('connection_id'):
            result[record['connection_id']] = record
    return result


def preferred(host, personal):
    return personal or main_record(host)


def token_for(host, record):
    return host.TOKEN if record.get('channel') == 'main' else bots.cipher().decrypt(record['token'].encode()).decode()


def message(host, record, text):
    if record.get('channel') != 'main':
        return text
    settings = host.load_settings()
    teacher = host.current_teacher_id()
    profile = host.load_tenant_registry().get('teachers', {}).get(teacher, {})
    name = str(settings.get('company_name') or ' '.join(filter(None,
        [profile.get('first_name'), profile.get('last_name')])) or ('Преподаватель ' + teacher))[:128]
    return name + '\n\n' + text


def recipient_only(host, user_id):
    with host.DATA_LOCK:
        visitors = host._load_json_raw(os.path.join(host.BASE_DIR, 'main_invite_visitors.json'), {})
        return str(user_id) in visitors and str(user_id) not in host.registered_teacher_ids(include_legacy=True)


def accept_main(host, raw, sender, chat, update_id):
    """Called only with a Telegram polling update, never with browser-supplied identity."""
    fallback = 'Эта ссылка уже использована или устарела. Попросите преподавателя прислать новую.'
    match = re.fullmatch(r'join_([0-9]{1,20})_([A-Za-z0-9_-]{32})', raw)
    if (not match or chat.get('type') != 'private' or sender.get('is_bot')
            or type(sender.get('id')) is not int or sender['id'] != chat.get('id')):
        return fallback
    teacher = match.group(1)
    with host.DATA_LOCK:
        if teacher not in host.registered_teacher_ids(include_legacy=True):
            return fallback
        with host.teacher_scope(teacher):
            path = os.path.join(host.tenant_root(), 'personal_bot_links.json')
            links = host._load_json_raw(path, {'invites': {}, 'bindings': {}, 'updates': {}})
            record = main_record(host)
            if not record:
                return fallback
            update_key = record['connection_id'] + ':' + str(update_id)
            if update_key in links['updates']:
                return None
            digest = hashlib.sha256(raw.encode()).hexdigest()
            invite = links['invites'].get(digest)
            if not (invite and invite['expires_at'] > time.time()
                    and invite['connection_id'] == record['connection_id']
                    and invite['student_id'] in host.load_json(host.STUDENTS_FILE)):
                return fallback
            visitors_path = os.path.join(host.BASE_DIR, 'main_invite_visitors.json')
            visitors = host._load_json_raw(visitors_path, {})
            visitors[str(sender['id'])] = True
            host._save_json_raw(visitors_path, visitors)
            key = hashlib.sha256(f"{record['connection_id']}:{invite['student_id']}:{invite['role']}:{sender['id']}".encode()).hexdigest()
            links['bindings'].setdefault(key, {
                'student_id': invite['student_id'], 'role': invite['role'],
                'connection_id': record['connection_id'], 'telegram_id': str(sender['id']),
                'chat_id': str(chat['id']), 'name': str(sender.get('first_name', ''))[:128],
                'username': str(sender.get('username', ''))[:64], 'state': 'pending'})
            del links['invites'][digest]
            links['updates'][update_key] = int(time.time())
            links['updates'] = dict(list(links['updates'].items())[-2000:])
            host._save_json_raw(path, links)
            settings = host.load_settings()
            role = invite['role']
            english = str(sender.get('language_code', '')).startswith('en')
            welcome = ('Hi! Thanks for connecting 😊 I’ll confirm your connection soon.' if english else
                       'Здравствуйте! Спасибо, что подключились 😊 Скоро я подтвержу подключение, и сюда будут приходить сообщения о занятиях.')
            text = str(settings.get(role + '_binding_template') or welcome).replace('{name}', str(sender.get('first_name', ''))[:128])
            return message(host, record, text)
