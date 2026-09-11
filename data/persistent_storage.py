"""Separate mutable data from deployable code; no implicit production seeding."""
import json
import os
from pathlib import Path

READY_FILE = '.temli-storage-ready.json'


def storage_path(code_dir, environ=None):
    env = os.environ if environ is None else environ
    explicit = env.get('TEMLI_DATA_DIR', '').strip()
    volume = env.get('DATA_DIR', '').strip()
    if explicit:
        path = Path(explicit)
    elif volume:
        path = Path(volume) / 'temli'
    elif os.name == 'posix' and Path(code_dir).resolve() == Path('/app'):
        # A missing environment variable must not put BotHost back into /app.
        path = Path('/app/data/temli')
    else:
        return Path(code_dir).resolve(), False
    if not path.is_absolute():
        raise RuntimeError('TEMLI storage directory must be absolute.')
    path = path.resolve()
    if path == Path(code_dir).resolve():
        raise RuntimeError('TEMLI persistent storage must be separate from application code.')
    return path, True


def resolve_storage_root(code_dir, environ=None):
    root, persistent = storage_path(code_dir, environ)
    if persistent:
        try:
            ready = json.loads((root / READY_FILE).read_text(encoding='utf-8'))
            if ready.get('schema') != 1 or ready.get('state') != 'ready':
                raise ValueError('Invalid storage marker')
            required = ready.get('required_files')
            if not isinstance(required, list) or not required:
                raise ValueError('Missing storage manifest')
            if not {'schedule.json', 'students.json', 'settings.json', 'teacher_registry.json'}.issubset(required):
                raise ValueError('Incomplete storage manifest')
            for name in required:
                part = Path(name)
                if part.is_absolute() or '..' in part.parts or not (root / part).resolve().is_relative_to(root) or not (root / part).is_file():
                    raise ValueError('Missing migrated data file')
        except (OSError, ValueError, TypeError, AttributeError):
            raise RuntimeError(
                'TEMLI: постоянное хранилище не подготовлено или неполно. '
                'Запуск остановлен во избежание пустого расписания. '
                'Сначала выполните migrate_storage.py; не удаляйте данные.'
            ) from None
    return str(root)
