"""Explicit, deduplicated messages through a teacher's bot."""
import datetime
import os
import re
import hashlib
from flask import request, jsonify
import personal_bots as bots
import invitation_channels as channels


def render_template(value, fallback, replacements):
    text = str(value or fallback).strip()
    for key, replacement in replacements.items():
        text = text.replace("{" + key + "}", str(replacement or ""))
    return text


def send_scheduled_notifications(host, now, kinds=('reminder', 'end')):
    # Each teacher is isolated; delivery uses the recipient's original channel.
    for teacher in host.registered_teacher_ids(include_legacy=True):
        try:
            if 'reminder' in kinds:
                _send_teacher_block_reminder(host, str(teacher), now)
            _send_teacher_notifications(host, str(teacher), now, kinds)
        except Exception:
            # Provider exceptions and credentials must not enter logs.
            continue


def _send_teacher_block_reminder(host, teacher, now):
    """Notify the teacher once per work block, never once per consecutive lesson."""
    with host.teacher_scope(teacher), host.DATA_LOCK:
        settings = host.load_settings()
        if settings.get('teacher_block_reminders') is not True or not str(host.TOKEN or ''):
            return
        lessons = []
        for lesson in host.load_json(host.DATA_FILE).get(now.strftime('%Y-%m-%d'), []):
            if host.is_personal_event(lesson) or lesson.get('cancelled'):
                continue
            try:
                start = datetime.datetime.strptime(now.strftime('%Y-%m-%d') + ' ' + lesson['time'], '%Y-%m-%d %H:%M')
                start = now.tzinfo.localize(start) if hasattr(now.tzinfo, 'localize') else start.replace(tzinfo=now.tzinfo)
                end = start + datetime.timedelta(minutes=int(lesson.get('duration', 60)))
            except (ValueError, TypeError, KeyError):
                continue
            lessons.append((start, end, lesson))
        lessons.sort(key=lambda item: item[0])
        gap = datetime.timedelta(minutes=int(settings.get('teacher_block_gap_minutes', 60)))
        lead = datetime.timedelta(minutes=int(settings.get('teacher_block_reminder_minutes', 30)))
        previous_end = None
        selected = None
        for start, end, lesson in lessons:
            starts_block = previous_end is None or start - previous_end > gap
            if starts_block and 0 <= (now - (start - lead)).total_seconds() < 300:
                selected = (start, lesson)
                break
            previous_end = max(previous_end, end) if previous_end else end
        if not selected:
            return
        start, lesson = selected
        path = os.path.join(host.tenant_root(), 'personal_notification_log.json')
        log = host._load_json_raw(path, {})
        key = 'teacher-block-' + hashlib.sha256(
            f"{teacher}:{start.isoformat()}:{lesson.get('id')}".encode()).hexdigest()
        if key in log:
            return
        log[key] = 'unknown'
        host._save_json_raw(path, log)
        title = str(lesson.get('group_name') or lesson.get('student') or 'занятие')
        text = f"Через 30 минут начинается рабочий блок: {title} · {start.strftime('%H:%M')}."
    try:
        bots.telegram_info(host.TOKEN, 'sendMessage', {'chat_id': int(teacher), 'text': text})
    except (bots.ConnectionError, TypeError, ValueError):
        return
    with host.teacher_scope(teacher), host.DATA_LOCK:
        log = host._load_json_raw(path, {})
        log[key] = 'sent'
        host._save_json_raw(path, log)


def send_lesson_end_notifications(host, now):
    send_scheduled_notifications(host, now, ('end',))


def _send_teacher_notifications(host, teacher, now, kinds):
    with host.teacher_scope(teacher):
        with host.DATA_LOCK:
            host.recover_payment_transaction()
            record = host._load_json_raw(os.path.join(host.BASE_DIR, 'personal_bots.json'), {}).get(teacher)
            available = channels.records(host, record)
            if not available:
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
                            if kind == 'reminder' and lesson.get('reminder_enabled') is False:
                                continue
                            enabled = info.get('parent_lesson_end' if kind == 'end' else 'student_reminders') is True
                            due = end if kind == 'end' else reminder
                            if not enabled or not 0 <= (now - due).total_seconds() < 300:
                                continue
                            if kind == 'reminder' and now >= end:
                                continue
                            role = 'parent' if kind == 'end' else 'student'
                            recipients = [b for b in links.get('bindings', {}).values() if b.get('student_id') == sid and b.get('role') == role and b.get('state') == 'active' and b.get('connection_id') in available]
                            if role == 'student' and len(recipients) != 1:
                                continue
                            english = settings.get('language') == 'en'
                            if kind == 'end':
                                fallback = ('Hello! Today’s lesson was held from {start} to {end}.' if english
                                            else 'Приветствую! Сегодня было проведено занятие с {start} до {end}.')
                                text = render_template(settings.get('parent_lesson_end_template'), fallback, {
                                    'start': start.strftime('%H:%M'), 'end': end.strftime('%H:%M')
                                })
                            else:
                                fallback = 'Reminder: lesson at {time}.' if english else 'Напоминание: занятие в {time}.'
                                template = str(settings.get('student_reminder_template') or '')
                                link = info.get('zoom_link') or lesson.get('zoom_link') or settings.get('zoom_link')
                                has_link_placeholder = '{link}' in template
                                text = render_template(template, fallback, {
                                    'time': start.strftime('%H:%M'), 'link': link or ''
                                })
                                if link and not has_link_placeholder:
                                    text += '\n' + str(link)
                            for recipient in recipients:
                                key = kind + '-' + hashlib.sha256(f"{recipient['connection_id']}:{date}:{lesson.get('id')}:{start.isoformat()}:{sid}:{recipient['chat_id']}".encode()).hexdigest()
                                if key not in log:
                                    log[key] = 'unknown'
                                    channel = available[recipient['connection_id']]
                                    jobs.append((key, recipient['chat_id'], channels.message(host, channel, text), channel))
            if not jobs:
                return
            host._save_json_raw(path, log)
        for key, chat, text, channel in jobs:
            try:
                token = channels.token_for(host, channel)
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
                available = channels.records(host, record)
                if not available:
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
                matches = [b for b in links.get('bindings', {}).values() if b.get('student_id') == student and b.get('role') == role and b.get('state') == 'active' and b.get('connection_id') in available]
                if not matches:
                    raise bots.ConnectionError('recipient_missing')
                if len(matches) != 1:
                    raise bots.ConnectionError('recipient_ambiguous')
                settings = host.load_settings()
                english = settings.get('language') == 'en'
                if action == 'teacher_delay':
                    start = datetime.datetime.strptime(str(data['date']) + ' ' + lesson['time'], '%Y-%m-%d %H:%M')
                    new_time = (start + datetime.timedelta(minutes=minutes)).strftime('%H:%M')
                    text = f'I’m running a little late. We’ll start at {new_time}.' if english else f'Немного задержусь. Начнём занятие в {new_time}.'
                elif role == 'student':
                    text = 'The lesson has started. Can you join?' if english else 'Занятие уже началось. Сможешь подключиться?'
                else:
                    text = 'The lesson has started, but your child hasn’t joined yet. Will they be able to join?' if english else 'Занятие уже началось, но ребёнок пока не подключился. Подскажите, сможет присоединиться?'
                template_key = 'teacher_delay_template' if action == 'teacher_delay' else 'student_delay_template' if role == 'student' else 'parent_delay_template'
                text = render_template(settings.get(template_key), text, {'time': new_time if action == 'teacher_delay' else lesson['time']})
                text = channels.message(host, available[matches[0]['connection_id']], text)
                path = os.path.join(host.tenant_root(), 'personal_notification_log.json')
                log = host._load_json_raw(path, {})
                if key in log:
                    return jsonify(status='ok', delivery=log[key])
                token = channels.token_for(host, available[matches[0]['connection_id']])
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
