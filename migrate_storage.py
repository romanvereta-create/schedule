"""Copy legacy TEMLI data, preserving originals and refusing overwrite.

Offline: copy a restored backup with --offline.
BotHost: prepare keeps the legacy data lock until container replacement.
Do not edit the old app during preparation or restart the old version afterward.
No dependencies, imports of bot.py, Telegram calls, or secret output.
"""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

from persistent_storage import READY_FILE, resolve_storage_root

DIRECTORIES = ('teacher_data', 'receipts', 'receipt_assets')
CORE = ('schedule.json', 'students.json', 'settings.json', 'teacher_registry.json')


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


@contextlib.contextmanager
def source_lock(source, timeout=30):
    with (source / '.schedule_data.lock').open('a+b') as handle:
        if os.name == 'nt':
            import msvcrt
            if handle.tell() == 0:
                handle.write(b'0')
                handle.flush()
        else:
            import fcntl
        deadline = time.monotonic() + timeout
        while True:
            try:
                if os.name == 'nt':
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Data busy; migration did not start.') from None
                time.sleep(0.1)
        try:
            yield
        finally:
            if os.name == 'nt':
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def inventory(source):
    paths = []
    for p in source.iterdir():
        if p.name in DIRECTORIES:
            if p.is_symlink() or not p.is_dir():
                raise RuntimeError('Invalid data directory')
            paths.extend(x for x in p.rglob('*') if x.is_file() or x.is_symlink())
        elif p.name.endswith(('.json', '.json.bak', '.xlsx', '.xlsx.bak')):
            paths.append(p)
    for p in paths:
        if p.is_symlink() or not p.is_file() or not p.resolve().is_relative_to(source):
            raise RuntimeError('Unsafe data file')
        if p.name == '.payment_transaction.json':
            raise RuntimeError('Unfinished payment transaction. Recover with the old app first.')
    for name in CORE:
        if source / name not in paths:
            raise RuntimeError('Missing required source file: ' + name)
    return sorted(paths)


def validate(path):
    if path.name.endswith(('.json', '.json.bak')):
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(value, (dict, list)):
            raise RuntimeError('Invalid JSON data structure')
    elif path.name.endswith(('.xlsx', '.xlsx.bak')):
        with zipfile.ZipFile(path) as workbook:
            if workbook.testzip() is not None:
                raise RuntimeError('Damaged workbook')


def copy_locked(source, destination):
    source, destination = source.resolve(), destination.resolve()
    if not source.is_dir() or source == destination or source.is_relative_to(destination):
        raise RuntimeError('Invalid source/destination')
    if destination.exists():
        raise RuntimeError('Destination already exists; nothing overwritten.')
    paths = inventory(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.temli-migration-', dir=destination.parent))
    hashes = {}
    for original in paths:
        relative = original.relative_to(source)
        target = stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)
        validate(target)
        with target.open('r+b') as copied:
            os.fsync(copied.fileno())
        before = digest(original)
        if before != digest(target):
            raise RuntimeError('Source changed while copying; destination not activated.')
        hashes[relative.as_posix()] = before
    # Include empty tenant/receipt directories, without code, old archives or /data placeholders.
    for name in DIRECTORIES:
        base = source / name
        if base.is_dir():
            (stage / name).mkdir(exist_ok=True)
            for folder in base.rglob('*'):
                if folder.is_dir():
                    if folder.is_symlink():
                        raise RuntimeError('Unsafe directory')
                    (stage / folder.relative_to(source)).mkdir(parents=True, exist_ok=True)
    if [str(p.relative_to(source)) for p in inventory(source)] != [str(p.relative_to(source)) for p in paths]:
        raise RuntimeError('Source file list changed; destination not activated.')
    if any(digest(source / name) != value for name, value in hashes.items()):
        raise RuntimeError('Source changed; destination not activated.')
    required = sorted(name for name in hashes if name.endswith(('.json', '.xlsx')))
    manifest = dict(schema=1, state='ready', required_files=required, snapshot_sha256=hashes)
    with (stage / READY_FILE).open('x', encoding='utf-8') as f:
        json.dump(manifest, f, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    # Sibling rename makes the verified tree visible in one operation.
    stage.rename(destination)
    if os.name == 'posix':
        descriptor = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return {'files': len(hashes), 'teacher_folders': sum(p.is_dir() for p in (destination/'teacher_data').iterdir()) if (destination/'teacher_data').exists() else 0}


def copy_offline(source, destination):
    with source_lock(source):
        return copy_locked(source, destination)


def status_path(destination):
    return destination.parent / '.temli-migration-status.json'


def write_status(destination, value):
    path = status_path(destination)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value), encoding='utf-8')
    os.replace(temporary, path)


def hold(source, destination):
    try:
        with source_lock(source):
            result = copy_locked(source, destination)
            # Linux BotHost: process survives the terminal session, is killed by
            # container replacement. Do not release while the old code can write.
            while True:
                write_status(destination, dict(state='READY_LOCK_HELD', pid=os.getpid(), heartbeat=time.time(), **result))
                time.sleep(2)
    except Exception as error:
        write_status(destination, dict(state='FAILED', error=type(error).__name__))
        raise


def migration_status(source, destination):
    status = json.loads(status_path(destination).read_text())
    if status.get('state') != 'READY_LOCK_HELD':
        return status
    if time.time() - status.get('heartbeat', 0) > 15:
        return {'state': 'HOLD_LOST_DO_NOT_DEPLOY'}
    try:
        with source_lock(source, timeout=0):
            return {'state': 'HOLD_LOST_DO_NOT_DEPLOY'}
    except RuntimeError:
        pass  # Exclusive source lock is still held.
    resolve_storage_root(source, {'TEMLI_DATA_DIR': str(destination)})
    manifest = json.loads((destination / READY_FILE).read_text())
    expected = manifest['snapshot_sha256']
    if set(expected) != {p.relative_to(source).as_posix() for p in inventory(source)}:
        return {'state': 'SOURCE_CHANGED_DO_NOT_DEPLOY'}
    if any(digest(source / n) != h or digest(destination / n) != h for n, h in expected.items()):
        return {'state': 'SOURCE_CHANGED_DO_NOT_DEPLOY'}
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['copy', 'prepare', 'status', '_hold'])
    parser.add_argument('--source', type=Path, default=Path('/app'))
    parser.add_argument('--destination', type=Path, default=Path('/app/data/temli'))
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    source, destination = args.source.resolve(), args.destination.resolve()
    if args.action == 'copy':
        if not args.offline:
            parser.error('copy requires --offline: use only a stopped source or restored backup')
        print(json.dumps(copy_offline(source, destination)))
    elif args.action == '_hold':
        hold(source, destination)
    elif args.action == 'prepare':
        if os.name != 'posix':
            parser.error('prepare is only supported on Linux BotHost')
        if destination.exists() or status_path(destination).exists():
            parser.error('Previous preparation exists. Use status; do not overwrite it.')
        destination.parent.mkdir(parents=True, exist_ok=True)
        write_status(destination, {'state': 'STARTING'})
        with (destination.parent / '.temli-migration.log').open('a') as log:
            subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '_hold', '--source', str(source), '--destination', str(destination)], start_new_session=True, stdin=subprocess.DEVNULL, stdout=log, stderr=log, close_fds=True)
        for _ in range(100):
            status = json.loads(status_path(destination).read_text())
            if status['state'] != 'STARTING':
                break
            time.sleep(0.1)
        print(json.dumps(status))
    else:
        print(json.dumps(migration_status(source, destination)))


if __name__ == '__main__':
    main()
