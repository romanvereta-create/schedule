"""Read-only post-deploy verification for TEMLI persistent storage.

Prints counts and generic errors only. It never prints names, notes, tokens,
Telegram IDs, file contents, or environment values.
"""
import argparse
import json
import os
from pathlib import Path
import zipfile

from persistent_storage import READY_FILE, resolve_storage_root


def json_object(path):
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError('expected object')
    return value


def inspect_storage(root, environ=None, minimums=None, check_key=True):
    env = os.environ if environ is None else environ
    minimums = minimums or {}
    root = Path(root).resolve()
    report = {
        'status': 'ok', 'storage': str(root), 'marker': False,
        'registered_teachers': 0, 'teacher_directories': 0,
        'lesson_records': 0, 'student_records': 0,
        'readable_books': 0, 'personal_bots': 0,
        'pending_payment_transactions': 0, 'errors': [],
    }
    try:
        resolve_storage_root('/app', {'TEMLI_DATA_DIR': str(root)})
        report['marker'] = True
        marker = json_object(root / READY_FILE)
        required = marker['required_files']
    except Exception:
        report['errors'].append('storage_marker_invalid')
        required = []

    try:
        registry = json_object(root / 'teacher_registry.json')
        teachers = registry.get('teachers')
        if not isinstance(teachers, dict):
            raise ValueError('invalid teachers')
        report['registered_teachers'] = len(teachers)
    except Exception:
        report['errors'].append('teacher_registry_invalid')

    teacher_root = root / 'teacher_data'
    try:
        directories = [path for path in teacher_root.iterdir() if path.is_dir() and not path.is_symlink()]
        report['teacher_directories'] = len(directories)
    except OSError:
        report['errors'].append('teacher_directory_invalid')
        directories = []

    tenant_roots = [root, *directories]
    for tenant in tenant_roots:
        try:
            schedule_path = tenant / 'schedule.json'
            if schedule_path.exists():
                schedule = json_object(schedule_path)
                if any(not isinstance(items, list) for items in schedule.values()):
                    raise ValueError('invalid schedule')
                report['lesson_records'] += sum(len(items) for items in schedule.values())
            students_path = tenant / 'students.json'
            if students_path.exists():
                report['student_records'] += len(json_object(students_path))
        except Exception:
            report['errors'].append('tenant_json_invalid')
            break

    for path in root.rglob('*.json'):
        try:
            relative = path.relative_to(root)
            if path.is_symlink() or '..' in relative.parts:
                raise ValueError('unsafe path')
            json.loads(path.read_text(encoding='utf-8-sig'))
        except Exception:
            report['errors'].append('json_file_invalid')
            break

    for path in root.rglob('*.xlsx'):
        try:
            with zipfile.ZipFile(path) as workbook:
                if workbook.testzip() is not None:
                    raise ValueError('CRC')
            report['readable_books'] += 1
        except Exception:
            report['errors'].append('workbook_invalid')
            break

    report['pending_payment_transactions'] = len(list(root.rglob('.payment_transaction.json')))
    if report['pending_payment_transactions']:
        report['errors'].append('payment_recovery_pending')

    personal_path = root / 'personal_bots.json'
    try:
        personal = json_object(personal_path) if personal_path.exists() else {}
        report['personal_bots'] = len(personal)
        if personal and check_key:
            from cryptography.fernet import Fernet
            cipher = Fernet(env['TEMLI_BOT_ENCRYPTION_KEY'].encode('ascii'))
            for record in personal.values():
                cipher.decrypt(record['token'].encode('ascii'))
                webhook = record.get('webhook') or {}
                if webhook.get('secret'):
                    cipher.decrypt(webhook['secret'].encode('ascii'))
    except Exception:
        report['errors'].append('personal_bot_key_or_data_invalid')

    # The migration marker names the exact snapshot files. Existing files may
    # legitimately change after launch, so hashes are not compared here.
    if any(not (root / name).is_file() for name in required):
        report['errors'].append('required_file_missing')

    for key, minimum in minimums.items():
        if report.get(key, 0) < minimum:
            report['errors'].append('below_minimum_' + key)

    report['errors'] = sorted(set(report['errors']))
    if report['errors']:
        report['status'] = 'error'
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--storage', default='')
    parser.add_argument('--minimum-teachers', type=int, default=25)
    parser.add_argument('--minimum-lessons', type=int, default=3291)
    parser.add_argument('--minimum-students', type=int, default=93)
    parser.add_argument('--minimum-books', type=int, default=6)
    args = parser.parse_args()
    root = args.storage or os.getenv('TEMLI_DATA_DIR') or str(Path(os.getenv('DATA_DIR', '/app/data')) / 'temli')
    minimums = {
        'registered_teachers': args.minimum_teachers,
        'lesson_records': args.minimum_lessons,
        'student_records': args.minimum_students,
        'readable_books': args.minimum_books,
    }
    report = inspect_storage(root, minimums=minimums)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report['status'] == 'ok' else 1)


if __name__ == '__main__':
    main()
