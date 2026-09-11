"""Explicit, deduplicated messages through a teacher's bot."""
import datetime
import os
import re
import hashlib
from flask import request, jsonify
import personal_bots as bots

def send_scheduled_notifications(host, now, kinds=('reminder', 'end')):
    # Each teacher is isolated, including failures. No fallback to the hub bot.
    for teacher in host.registered_teacher_ids(include_legacy=True):
        try:
            _send_teacher_notifications(host, str(teacher), now, kinds)
        except Exception:
            # Provider exceptions and credentials must not enter logs.
            continue


def send_lesson_end_notifications(host, now):
    send_scheduled_notifications(host, now, ('end',))


def _send_teacher_notifications(host, teacher, now, kinds):
    with host.teacher_scope(teacher):
        with host.DATA_LOCK:
            host.recover_payment_transaction()
            record = host._load_json_raw(os.path.join(host.BASE_DIR, 'personal_bots.json'), {}).get(teacher)
            if not record or not record.get('connection_id'):
                return
            settings = host.load_settings()
            students = host.load_json(host.STUDENTS_FILE)
            schedule = host.load_json(host.DATA_FILE)
            links = host._load_json_raw(os.path.join(host.tenant_root(), 'personal_bot_links.json'), {})
            path = os.path.join(host.tenant_root(), 'personal_notification_log.json')
            log = host._load_json_raw(path, {})
            jobs = []
            for date, lessons in schedule.items():
                try:
                    day = datetime.date.fromisoformat(date)
                except (ValueError, TypeError):
                    continue
                if not -1 <= (day - now.date()).days <= 8:
                    continue
                for lesson in lessons:
                    if host.is_personal_event(lesson) or lesson.get('cancelled'):
                        continue
                    try:
                        start = datetime.datetime.strptime(date + ' ' + lesson['time'], '%Y-%m-%d %H:%M')
                        start = now.tzinfo.localize(start) if hasattr(now.tzinfo, 'localize') else start.replace(tzinfo=now.tzinfo)
                        end = start + datetime.timedelta(minutes=int(lesson.get('duration', 60)))
                        lead = max(0, min(10080, int(lesson.get('reminder_minutes', 60))))
                        reminder = start - datetime.timedelta(minutes=lead)
                    except (ValueError, TypeError, KeyError):
                        continue
                    members = lesson.get('group_members', []) if lesson.get('lesson_type') == 'group' else [{'student_id':lesson.get('student_id')}]
                    for member in members:
                        sid = str(member.get('student_id', ''))
                        info = host.get_student_record(students, sid)
                        for kind in kinds:
                            enabled = info.get('parent_lesson_end' if kind == 'end' else 'student_reminders') is True
                            due = end if kind == 'end' else reminder
                            if not enabled or not 0 <= (now - due).total_seconds() < 300:
                                continue
                            if kind == 'reminder' and now >= end:
                                continue
                            role = 'parent' if kind == 'end' else 'student'
                            recipients = [b for b in links.get('bindings', {}).values() if b.get('student_id') == sid and b.get('role') == role and b.get('state') == 'active' and b.get('connection_id') == record['connection_id']]
                            if role == 'student' and len(recipients) != 1:
                                continue
                            english = settings.get('language') == 'en'
                            if kind == 'end':
                                text = (f'Hello! Today’s lesson was held from {start:%H:%M} to {end:%H:%M}.' if english
                                        else f'Приветствую! Сегодня было проведено занятие с {start:%H:%M} до {end:%H:%M}.')
                            else:
                                text = f'Reminder: lesson at {start:%H:%M}.' if english else f'Напоминание: занятие в {start:%H:%M}.'
                                link = info.get('zoom_link') or lesson.get('zoom_link') or settings.get('zoom_link')
                                if link:
                                    text += '\n' + str(link)
                            for recipient in recipients:
                                key = kind + '-' + hashlib.sha256(f"{record['connection_id']}:{date}:{lesson.get('id')}:{start.isoformat()}:{sid}:{recipient['chat_id']}".encode()).hexdigest()
                                if key not in log:
                                    log[key] = 'unknown'
                                    jobs.append((key, recipient['chat_id'], text))
            if not jobs:
                return
            token = bots.cipher().decrypt(record['token'].encode()).decode()
            host._save_json_raw(path, log)
        for key, chat, text in jobs:
            try:
                bots.telegram_info(token, 'sendMessage', {'chat_id':chat, 'text':text})
            except bots.ConnectionError:
                continue
            with host.DATA_LOCK:
                log = host._load_json_raw(path, {})
                log[key] = 'sent'
                host._save_json_raw(path, log)

def register_routes(host, registry, identity):
    @host.flask_app.route('/api/personal_notification', methods=['POST'])
    def notify():
        try:
            teacher = identity()
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                raise bots.ConnectionError('invalid_request')
            action, role, minutes = data.get('action'), data.get('role'), data.get('minutes')
            if action not in ('teacher_delay', 'student_delay') or role not in ('student', 'parent'):
                raise bots.ConnectionError('invalid_request')
            if action == 'teacher_delay' and (role != 'student' or type(minutes) is not int or minutes not in (5, 10, 15)):
                raise bots.ConnectionError('invalid_request')
            key = str(data.get('request_id', ''))
            if not re.fullmatch(r'[A-Za-z0-9_-]{16,100}', key):
                raise bots.ConnectionError('invalid_request')
            with host.teacher_scope(teacher), host.DATA_LOCK:
                record = registry().get(teacher)
                if not record:
                    raise bots.ConnectionError('bot_required')
                lessons = host.load_json(host.DATA_FILE).get(str(data.get('date', '')), [])
                lesson = next((x for x in lessons if str(x.get('id')) == str(data.get('lesson_id'))), None)
                if not lesson or host.is_personal_event(lesson) or lesson.get('cancelled'):
                    raise bots.ConnectionError('lesson_missing')
                student = str(data.get('student_id', ''))
                members = [str(m.get('student_id')) for m in lesson.get('group_members', [])] if lesson.get('lesson_type') == 'group' else [str(lesson.get('student_id'))]
                if student not in members:
                    raise bots.ConnectionError('student_missing')
                links = host._load_json_raw(os.path.join(host.tenant_root(), 'personal_bot_links.json'), {})
                matches = [b for b in links.get('bindings', {}).values() if b.get('student_id') == student and b.get('role') == role and b.get('state') == 'active' and b.get('connection_id') == record.get('connection_id')]
                if not matches:
                    raise bots.ConnectionError('recipient_missing')
                if len(matches) != 1:
                    raise bots.ConnectionError('recipient_ambiguous')
                english = host.load_settings().get('language') == 'en'
                if action == 'teacher_delay':
                    start = datetime.datetime.strptime(str(data['date']) + ' ' + lesson['time'], '%Y-%m-%d %H:%M')
                    new_time = (start + datetime.timedelta(minutes=minutes)).strftime('%H:%M')
                    text = f'I’m running a little late. We’ll start at {new_time}.' if english else f'Немного задержусь. Начнём занятие в {new_time}.'
                elif role == 'student':
                    text = 'The lesson has started. Can you join?' if english else 'Занятие уже началось. Сможешь подключиться?'
                else:
                    text = 'The lesson has started, but your child hasn’t joined yet. Will they be able to join?' if english else 'Занятие уже началось, но ребёнок пока не подключился. Подскажите, сможет присоединиться?'
                path = os.path.join(host.tenant_root(), 'personal_notification_log.json')
                log = host._load_json_raw(path, {})
                if key in log:
                    return jsonify(status='ok', delivery=log[key])
                token = bots.cipher().decrypt(record['token'].encode()).decode()
                chat = matches[0]['chat_id']
                log[key] = 'unknown'
                host._save_json_raw(path, log)
            try:
                bots.telegram_info(token, 'sendMessage', {'chat_id': chat, 'text': text})
            except bots.ConnectionError as error:
                if str(error) != 'telegram_unavailable':
                    return jsonify(status='error', code=str(error)), 400
                return jsonify(status='ok', delivery='unknown')
            with host.teacher_scope(teacher), host.DATA_LOCK:
                log = host._load_json_raw(path, {})
                log[key] = 'sent'
                host._save_json_raw(path, log)
            return jsonify(status='ok', delivery='sent')
        except bots.ConnectionError as error:
            return jsonify(status='error', code=str(error)), 400
        except Exception:
            return jsonify(status='error', code='notification_unavailable'), 503
