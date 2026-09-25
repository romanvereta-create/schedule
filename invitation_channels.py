"""Resolve the bot that a recipient actually joined; never silently migrate bindings."""
import os
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
    # Recipient communication is deliberately restricted to the teacher's
    # branded bot.  The main TEMLI bot must never be a delivery fallback.
    for record in (personal,):
        if record and record.get('channel') != 'main' and record.get('connection_id'):
            result[record['connection_id']] = record
    return result


def preferred(host, personal):
    return personal if personal and personal.get('channel') != 'main' else None


def token_for(host, record):
    if not record or record.get('channel') == 'main':
        raise bots.ConnectionError('bot_required')
    return bots.cipher().decrypt(record['token'].encode()).decode()


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
    """Reject legacy main-bot invite links without creating a binding."""
    return 'Эта ссылка больше не работает. Попросите преподавателя прислать ссылку на его бота.'
