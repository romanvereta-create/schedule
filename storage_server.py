"""Russian-side JSON storage service for the TEMLI split deployment."""
from __future__ import annotations

import hashlib
import base64
import binascii
import hmac
import json
import os
import re
import tempfile
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from flask import Flask, jsonify, request, send_file
from persistent_storage import READY_FILE


CORE_FILES = ("schedule.json", "students.json", "settings.json", "teacher_registry.json")
MAX_REQUEST_BYTES = 12 * 1024 * 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
BINARY_SUFFIXES = {'.xlsx', '.pdf', '.png', '.jpg', '.jpeg'}
MAX_BACKUP_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
BACKUP_NAME_RE = re.compile(r"^temli-\d{8}T\d{6}(?:\d{6})?Z-[a-z0-9-]{1,32}\.zip$")
PAYMENT_TRANSACTION_RE = re.compile(r'^[A-Za-z0-9_-]{16,80}$')


class StorageServiceError(RuntimeError):
    pass


def version_for(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def storage_root(environ=None):
    environ = os.environ if environ is None else environ
    explicit = str(environ.get("TEMLI_DATA_DIR", "") or "").strip()
    volume = str(environ.get("DATA_DIR", "") or "").strip()
    root = Path(explicit) if explicit else Path(volume) / "temli" if volume else None
    if root is None or not root.is_absolute():
        raise StorageServiceError("Set absolute TEMLI_DATA_DIR or DATA_DIR")
    return root.resolve()


def _atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="temli_storage_", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            json.dump(value, target, ensure_ascii=False, indent=2)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def initialize_empty(root):
    root.mkdir(parents=True, exist_ok=True)
    existing = [part for part in root.iterdir() if part.name != READY_FILE]
    if existing:
        raise StorageServiceError("Refusing to initialize a non-empty storage directory")
    for name in CORE_FILES:
        _atomic_json(root / name, {})
    _atomic_json(root / READY_FILE, {
        "schema": 1,
        "state": "ready",
        "required_files": list(CORE_FILES),
        "mode": "remote-json-test",
    })


def validate_root(root):
    try:
        marker = json.loads((root / READY_FILE).read_text(encoding="utf-8"))
        required = marker.get("required_files")
        if marker.get("schema") != 1 or marker.get("state") != "ready":
            raise ValueError()
        if not isinstance(required, list) or not set(CORE_FILES).issubset(required):
            raise ValueError()
        for name in required:
            if not (root / name).is_file():
                raise ValueError()
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        raise StorageServiceError("TEMLI storage is not initialized or is incomplete") from None


def _safe_json_path(root, raw):
    path = _safe_data_path(root, raw)
    if path.suffix.lower() != '.json':
        raise StorageServiceError('invalid_path')
    return path


def _safe_data_path(root, raw):
    raw = str(raw or "").replace("\\", "/")
    part = PurePosixPath(raw)
    if (not raw or part.is_absolute() or ".." in part.parts or "." in part.parts
            or ':' in raw or any(item in {'', '.', '..'} for item in raw.split('/'))
            or any(not item or len(item) > 128 for item in part.parts)
            or len(raw) > 512):
        raise StorageServiceError("invalid_path")
    path = (root / Path(*part.parts)).resolve()
    if not path.is_relative_to(root):
        raise StorageServiceError("invalid_path")
    return path


def _safe_binary_path(root, raw):
    path = _safe_data_path(root, raw)
    parts = path.relative_to(root).parts
    if len(parts) >= 3 and parts[0] == 'teacher_data':
        if not re.fullmatch(r'[1-9][0-9]*', parts[1]):
            raise StorageServiceError('invalid_path')
        parts = parts[2:]
    valid = (parts == ('book.xlsx',)
             or (len(parts) == 2 and parts[0] == 'receipt_assets'
                 and Path(parts[1]).stem in {'logo', 'signature', 'qrcode'}
                 and path.suffix.lower() in {'.png', '.jpg', '.jpeg'})
             or (len(parts) == 2 and parts[0] == 'receipts'
                 and re.fullmatch(r'[A-Za-z0-9_-]+\.pdf', parts[1])))
    if not valid:
        raise StorageServiceError('invalid_path')
    return path


def _atomic_bytes(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='temli_file_', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as target:
            target.write(raw)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def _archive_data_path(root, relative):
    path = _safe_data_path(root, relative)
    parts = path.relative_to(root).parts
    if any(part.startswith('.') for part in parts) and parts != (READY_FILE,):
        raise StorageServiceError('invalid_path')
    if path.suffix.lower() == '.json':
        return path
    return _safe_binary_path(root, relative)


def _payment_item_path(root, raw, kind):
    """Validate one file participating in a payment commit and return its scope."""
    path = _safe_data_path(root, raw)
    parts = path.relative_to(root).parts
    if len(parts) == 1:
        scope = root
        name = parts[0]
    elif (len(parts) == 3 and parts[0] == 'teacher_data'
          and re.fullmatch(r'[1-9][0-9]*', parts[1])):
        scope = root / parts[0] / parts[1]
        name = parts[2]
    else:
        raise StorageServiceError('invalid_payment_path')
    expected_kind = 'binary' if name == 'book.xlsx' else 'json'
    if name not in {'schedule.json', 'payments.json', 'book.xlsx'} or kind != expected_kind:
        raise StorageServiceError('invalid_payment_path')
    return path, scope, name


def _payment_version(path, kind):
    if not path.exists():
        return None
    if kind == 'binary':
        return _file_sha256(path)
    try:
        return version_for(json.loads(path.read_text(encoding='utf-8')))
    except (OSError, json.JSONDecodeError):
        raise StorageServiceError('corrupt_json') from None


def _payment_journal_path(scope, transaction_id):
    directory = scope / '.payment-transactions'
    directory.mkdir(parents=True, exist_ok=True)
    return directory / (transaction_id + '.json')


def _restore_payment_before(root, record):
    for item in record.get('items', []):
        path, _scope, _name = _payment_item_path(root, item.get('path'), item.get('kind'))
        if item.get('existed'):
            if item['kind'] == 'binary':
                raw = base64.b64decode(item.get('before'), validate=True)
                _atomic_bytes(path, raw)
            else:
                _atomic_json(path, item.get('before'))
        elif path.exists():
            path.unlink()


def _recover_payment_record(root, journal, record):
    if record.get('state') != 'prepared':
        return record
    items = record.get('items')
    if not isinstance(items, list) or not items:
        raise StorageServiceError('invalid_payment_journal')
    all_applied = all(
        _payment_version(_payment_item_path(root, item.get('path'), item.get('kind'))[0], item.get('kind'))
        == item.get('after_version')
        for item in items
    )
    if all_applied:
        record['state'] = 'committed'
        record['items'] = [
            {key: item[key] for key in ('path', 'kind', 'after_version')}
            for item in items
        ]
    else:
        _restore_payment_before(root, record)
        record['state'] = 'rolled_back'
    _atomic_json(journal, record)
    return record


def recover_payment_transactions(root):
    for journal in root.glob('**/.payment-transactions/*.json'):
        try:
            record = json.loads(journal.read_text(encoding='utf-8'))
            _recover_payment_record(root, journal, record)
        except (OSError, ValueError, TypeError, binascii.Error, json.JSONDecodeError,
                StorageServiceError):
            raise StorageServiceError('invalid_payment_journal') from None


def backup_root(root, environ=None):
    environ = os.environ if environ is None else environ
    explicit = str(environ.get("TEMLI_BACKUP_DIR", "") or "").strip()
    path = Path(explicit) if explicit else Path(root).resolve().parent / "temli-backups"
    if not path.is_absolute():
        raise StorageServiceError("TEMLI_BACKUP_DIR must be absolute")
    path = path.resolve()
    if path == Path(root).resolve() or path.is_relative_to(Path(root).resolve()):
        raise StorageServiceError("Backup directory must be outside TEMLI storage")
    return path


def _file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _backup_path(directory, raw_name):
    name = str(raw_name or "")
    if not BACKUP_NAME_RE.fullmatch(name):
        raise StorageServiceError("invalid_backup_name")
    path = (Path(directory).resolve() / name).resolve()
    if path.parent != Path(directory).resolve():
        raise StorageServiceError("invalid_backup_name")
    return path


def _snapshot_files(root):
    root = Path(root).resolve()
    files = []
    total = 0
    for path in sorted(root.rglob('*')):
        if '.payment-transactions' in path.parts:
            continue
        if path.suffix.lower() not in BINARY_SUFFIXES | {'.json'}:
            continue
        if path.is_symlink():
            raise StorageServiceError('Unsafe backup source')
        path = path.resolve()
        if not path.is_file() or not path.is_relative_to(root):
            continue
        relative = path.relative_to(root).as_posix()
        _archive_data_path(root, relative)
        raw = path.read_bytes()
        try:
            if path.suffix.lower() == '.json':
                json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise StorageServiceError("Cannot back up corrupt JSON: " + relative) from None
        total += len(raw)
        if total > MAX_BACKUP_UNCOMPRESSED_BYTES:
            raise StorageServiceError("Backup exceeds uncompressed size limit")
        files.append((relative, raw))
    if not files:
        raise StorageServiceError("No JSON files to back up")
    return files


def prune_backups(directory, retention):
    directory = Path(directory).resolve()
    retention = max(1, int(retention))
    archives = sorted(
        (path for path in directory.glob("temli-*.zip") if BACKUP_NAME_RE.fullmatch(path.name)),
        key=lambda path: path.name,
        reverse=True,
    )
    for stale in archives[retention:]:
        stale.unlink()


def create_backup(root, directory, *, reason="manual", retention=30):
    root = Path(root).resolve()
    directory = Path(directory).resolve()
    reason = re.sub(r"[^a-z0-9-]+", "-", str(reason).lower()).strip("-") or "manual"
    reason = reason[:32]
    directory.mkdir(parents=True, exist_ok=True)
    files = _snapshot_files(root)
    created = datetime.now(timezone.utc)
    name = "temli-" + created.strftime("%Y%m%dT%H%M%S%fZ") + "-" + reason + ".zip"
    target = directory / name
    manifest = {
        "schema": 2,
        "created_at": created.isoformat(),
        "reason": reason,
        "files": [
            {"path": relative, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            for relative, raw in files
        ],
    }
    fd, temporary = tempfile.mkstemp(prefix=".temli-backup-", suffix=".tmp", dir=directory)
    os.close(fd)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            for relative, raw in files:
                archive.writestr("data/" + relative, raw)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    prune_backups(directory, retention)
    return target, manifest


def inspect_backup(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise StorageServiceError("backup_not_found")
    try:
        with zipfile.ZipFile(path, "r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)) or "manifest.json" not in names:
                raise StorageServiceError("invalid_backup")
            if any(info.is_dir() for info in infos):
                raise StorageServiceError("invalid_backup")
            total = sum(info.file_size for info in infos)
            if total > MAX_BACKUP_UNCOMPRESSED_BYTES:
                raise StorageServiceError("invalid_backup")
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            if not isinstance(manifest, dict) or manifest.get("schema") not in (1, 2) or not isinstance(manifest.get("files"), list):
                raise StorageServiceError("invalid_backup")
            payload = {}
            expected_members = {"manifest.json"}
            for entry in manifest["files"]:
                if not isinstance(entry, dict):
                    raise StorageServiceError("invalid_backup")
                relative = str(entry.get("path", ""))
                part = PurePosixPath(relative)
                if (not relative or part.is_absolute() or ".." in part.parts or "." in part.parts
                        or any(not item or len(item) > 128 for item in part.parts)
                        or len(relative) > 512
                        or relative in payload):
                    raise StorageServiceError("invalid_backup")
                _archive_data_path(path.parent, relative)
                if manifest['schema'] == 1 and part.suffix.lower() != '.json':
                    raise StorageServiceError('invalid_backup')
                member = "data/" + relative
                expected_members.add(member)
                raw = archive.read(member)
                if len(raw) != entry.get("size") or hashlib.sha256(raw).hexdigest() != entry.get("sha256"):
                    raise StorageServiceError("invalid_backup")
                if part.suffix.lower() == '.json':
                    json.loads(raw.decode("utf-8"))
                payload[relative] = raw
            if set(names) != expected_members:
                raise StorageServiceError("invalid_backup")
    except (OSError, KeyError, TypeError, ValueError, UnicodeDecodeError,
            json.JSONDecodeError, zipfile.BadZipFile):
        raise StorageServiceError("invalid_backup") from None
    if not set(CORE_FILES).issubset(payload) or READY_FILE not in payload:
        raise StorageServiceError("incomplete_backup")
    return manifest, payload


def restore_backup(root, archive_path, directory, *, retention=30):
    root = Path(root).resolve()
    manifest, payload = inspect_backup(archive_path)
    marker = json.loads(payload[READY_FILE].decode("utf-8"))
    if not isinstance(marker, dict):
        raise StorageServiceError('invalid_backup_marker')
    required = marker.get("required_files")
    if (marker.get("schema") != 1 or marker.get("state") != "ready"
            or not isinstance(required, list)
            or any(not isinstance(item, str) for item in required)
            or not set(CORE_FILES).issubset(required)
            or not set(required).issubset(payload)):
        raise StorageServiceError("invalid_backup_marker")
    destinations = {relative: _archive_data_path(root, relative) for relative in payload}
    safety_path, _ = create_backup(root, directory, reason="pre-restore", retention=retention)
    for relative, raw in payload.items():
        destination = destinations[relative]
        if destination.exists():
            _atomic_bytes(Path(str(destination) + '.bak'), destination.read_bytes())
        _atomic_bytes(destination, raw)
    validate_root(root)
    return manifest, safety_path


def list_backups(directory):
    directory = Path(directory).resolve()
    result = []
    if not directory.is_dir():
        return result
    for path in sorted(directory.glob("temli-*.zip"), key=lambda item: item.name, reverse=True):
        if not BACKUP_NAME_RE.fullmatch(path.name):
            continue
        try:
            manifest, _ = inspect_backup(path)
            result.append({
                "name": path.name,
                "size": path.stat().st_size,
                "sha256": _file_sha256(path),
                "created_at": manifest.get("created_at"),
                "reason": manifest.get("reason"),
                "file_count": len(manifest["files"]),
            })
        except StorageServiceError:
            result.append({"name": path.name, "valid": False})
    return result


def start_backup_worker(root, directory, lock, *, interval, retention):
    stop = threading.Event()

    def run():
        while not stop.wait(interval):
            try:
                with lock:
                    create_backup(root, directory, reason="automatic", retention=retention)
            except Exception as error:
                print("TEMLI automatic backup failed: " + type(error).__name__, flush=True)

    thread = threading.Thread(target=run, name="temli-storage-backup", daemon=True)
    thread.start()
    return stop, thread


def create_app(root, token, *, initialize=False, backups=None, backup_retention=30):
    root = Path(root).resolve()
    token = str(token or "")
    if len(token) < 32:
        raise StorageServiceError("TEMLI_STORAGE_TOKEN must contain at least 32 characters")
    if initialize and not (root / READY_FILE).exists():
        initialize_empty(root)
    validate_root(root)
    recover_payment_transactions(root)

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES
    lock = threading.RLock()
    backups = backup_root(root) if backups is None else Path(backups).resolve()
    backup_retention = max(1, int(backup_retention))
    app.extensions["temli_storage_lock"] = lock
    app.extensions["temli_backup_root"] = backups
    app.extensions["temli_backup_retention"] = backup_retention
    # Backup archives are immutable after atomic creation. Cache the last
    # verified signature so frequent readiness probes do not reread the ZIP.
    backup_verification_cache = {"signature": None}

    @app.before_request
    def authenticate():
        if request.path == "/health":
            return None
        supplied = request.headers.get("Authorization", "")
        expected = "Bearer " + token
        if not hmac.compare_digest(supplied, expected):
            return jsonify(status="error", code="unauthorized"), 401
        if request.method in {"POST", "PUT", "PATCH"} and not request.is_json:
            return jsonify(status="error", code="json_required"), 415
        return None

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="temli-storage", schema=1,
                       capabilities=['json', 'json-batch-v1', 'files-v1',
                                     'payment-tx-v1', 'backup-v2',
                                     'authenticated-status-v1',
                                     'backup-integrity-status-v1'])

    @app.post("/v1/status")
    def authenticated_status():
        with lock:
            try:
                validate_root(root)
                archives = sorted(
                    (path for path in backups.glob("temli-*.zip")
                     if BACKUP_NAME_RE.fullmatch(path.name)),
                    key=lambda path: path.stat().st_mtime,
                    reverse=True,
                )
                latest = archives[0] if archives else None
                latest_age = None
                latest_verified = False
            except (OSError, StorageServiceError):
                return jsonify(status="error", code="storage_not_ready"), 503
            if latest is not None:
                try:
                    latest_stat = latest.stat()
                    latest_age = max(0, int(
                        datetime.now(timezone.utc).timestamp() - latest_stat.st_mtime
                    ))
                    signature = (
                        str(latest), latest_stat.st_dev, latest_stat.st_ino,
                        latest_stat.st_size, latest_stat.st_mtime_ns,
                    )
                    if backup_verification_cache["signature"] != signature:
                        inspect_backup(latest)
                        backup_verification_cache["signature"] = signature
                    latest_verified = True
                except (OSError, StorageServiceError):
                    return jsonify(
                        status="error", code="backup_verification_failed",
                    ), 503
        return jsonify(
            status="ok",
            service="temli-storage",
            backup={
                "count": len(archives),
                "latest_age_seconds": latest_age,
                "latest_verified": latest_verified,
            },
        )

    @app.post('/v1/files/read')
    def file_read():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify(status='error', code='invalid_request'), 400
        try:
            path = _safe_binary_path(root, body.get('path'))
            with lock:
                if not path.exists():
                    return jsonify(status='ok', exists=False, data=None, version=None)
                if path.stat().st_size > MAX_FILE_BYTES:
                    return jsonify(status='error', code='file_too_large'), 413
                raw = path.read_bytes()
                return jsonify(status='ok', exists=True,
                               data=base64.b64encode(raw).decode('ascii'),
                               version=hashlib.sha256(raw).hexdigest())
        except StorageServiceError as error:
            return jsonify(status='error', code=str(error)), 400

    @app.post('/v1/files/write')
    def file_write():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify(status='error', code='invalid_request'), 400
        try:
            path = _safe_binary_path(root, body.get('path'))
            if 'expected_version' not in body:
                return jsonify(status='error', code='expected_version_required'), 400
            raw = base64.b64decode(body.get('data', ''), validate=True)
            if not raw or len(raw) > MAX_FILE_BYTES:
                return jsonify(status='error', code='invalid_file_size'), 400
            with lock:
                actual = _file_sha256(path) if path.exists() else None
                if body['expected_version'] != actual:
                    return jsonify(status='error', code='version_conflict'), 409
                if path.exists():
                    _atomic_bytes(Path(str(path) + '.bak'), path.read_bytes())
                _atomic_bytes(path, raw)
                return jsonify(status='ok', version=hashlib.sha256(raw).hexdigest())
        except (StorageServiceError, ValueError, TypeError, binascii.Error):
            return jsonify(status='error', code='invalid_file_request'), 400

    @app.post('/v1/files/delete')
    def file_delete():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify(status='error', code='invalid_request'), 400
        try:
            path = _safe_binary_path(root, body.get('path'))
            if 'expected_version' not in body:
                return jsonify(status='error', code='expected_version_required'), 400
            with lock:
                existed = path.exists()
                actual = _file_sha256(path) if existed else None
                if body['expected_version'] != actual:
                    return jsonify(status='error', code='version_conflict'), 409
                if existed:
                    _atomic_bytes(Path(str(path) + '.bak'), path.read_bytes())
                    path.unlink()
                return jsonify(status='ok', existed=existed, version=None)
        except (StorageServiceError, OSError):
            return jsonify(status='error', code='invalid_file_request'), 400

    @app.post('/v1/transactions/payment')
    def payment_transaction():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify(status='error', code='invalid_request'), 400
        transaction_id = str(body.get('transaction_id', ''))
        request_items = body.get('items')
        if (not PAYMENT_TRANSACTION_RE.fullmatch(transaction_id)
                or not isinstance(request_items, list)
                or not 1 <= len(request_items) <= 3):
            return jsonify(status='error', code='invalid_payment_transaction'), 400
        try:
            normalized = []
            scopes = set()
            names = set()
            for item in request_items:
                if not isinstance(item, dict) or 'expected_version' not in item or 'data' not in item:
                    raise StorageServiceError('invalid_payment_transaction')
                kind = str(item.get('kind', ''))
                path, scope, name = _payment_item_path(root, item.get('path'), kind)
                if name in names:
                    raise StorageServiceError('duplicate_payment_path')
                names.add(name)
                scopes.add(scope)
                expected = item.get('expected_version')
                if expected is not None and not re.fullmatch(r'[0-9a-f]{64}', str(expected)):
                    raise StorageServiceError('invalid_expected_version')
                if kind == 'binary':
                    raw = base64.b64decode(item.get('data', ''), validate=True)
                    if not raw or len(raw) > MAX_FILE_BYTES:
                        raise StorageServiceError('invalid_file_size')
                    value = raw
                    after_version = hashlib.sha256(raw).hexdigest()
                else:
                    value = item['data']
                    # Ensure the value is JSON serializable before journaling.
                    json.dumps(value, ensure_ascii=False)
                    after_version = version_for(value)
                normalized.append({
                    'path': path,
                    'relative': path.relative_to(root).as_posix(),
                    'scope': scope,
                    'name': name,
                    'kind': kind,
                    'expected_version': expected,
                    'value': value,
                    'after_version': after_version,
                })
            if len(scopes) != 1 or 'schedule.json' not in names:
                raise StorageServiceError('invalid_payment_scope')
        except (StorageServiceError, ValueError, TypeError, binascii.Error):
            return jsonify(status='error', code='invalid_payment_transaction'), 400

        canonical = json.dumps(body, ensure_ascii=False, sort_keys=True,
                               separators=(',', ':')).encode('utf-8')
        request_hash = hashlib.sha256(canonical).hexdigest()
        scope = normalized[0]['scope']
        journal = _payment_journal_path(scope, transaction_id)
        with lock:
            if journal.exists():
                try:
                    record = json.loads(journal.read_text(encoding='utf-8'))
                    record = _recover_payment_record(root, journal, record)
                except (OSError, ValueError, TypeError, binascii.Error,
                        json.JSONDecodeError, StorageServiceError):
                    return jsonify(status='error', code='invalid_payment_journal'), 503
                if record.get('request_hash') != request_hash:
                    return jsonify(status='error', code='transaction_id_conflict'), 409
                if record.get('state') == 'committed':
                    return jsonify(status='ok', transaction_id=transaction_id,
                                   versions=record.get('versions', {}), idempotent=True)

            for item in normalized:
                try:
                    actual = _payment_version(item['path'], item['kind'])
                except StorageServiceError as error:
                    return jsonify(status='error', code=str(error)), 503
                if actual != item['expected_version']:
                    return jsonify(status='error', code='version_conflict'), 409

            record_items = []
            for item in normalized:
                existed = item['path'].exists()
                if item['kind'] == 'binary':
                    before = base64.b64encode(item['path'].read_bytes()).decode('ascii') if existed else None
                else:
                    before = json.loads(item['path'].read_text(encoding='utf-8')) if existed else None
                record_items.append({
                    'path': item['relative'], 'kind': item['kind'],
                    'existed': existed, 'before': before,
                    'after_version': item['after_version'],
                })
            versions = {item['relative']: item['after_version'] for item in normalized}
            record = {
                'schema': 1, 'state': 'prepared', 'transaction_id': transaction_id,
                'request_hash': request_hash, 'created_at': datetime.now(timezone.utc).isoformat(),
                'items': record_items, 'versions': versions,
            }
            _atomic_json(journal, record)
            try:
                for item in normalized:
                    if item['kind'] == 'binary':
                        _atomic_bytes(item['path'], item['value'])
                    else:
                        _atomic_json(item['path'], item['value'])
            except Exception:
                try:
                    _restore_payment_before(root, record)
                    record['state'] = 'rolled_back'
                    _atomic_json(journal, record)
                except Exception:
                    pass
                return jsonify(status='error', code='payment_commit_failed'), 503

            record['state'] = 'committed'
            record['items'] = [
                {key: item[key] for key in ('path', 'kind', 'after_version')}
                for item in record_items
            ]
            _atomic_json(journal, record)
            completed = sorted(journal.parent.glob('*.json'),
                               key=lambda value: value.stat().st_mtime, reverse=True)
            for old in completed[200:]:
                try:
                    old.unlink()
                except OSError:
                    pass
            return jsonify(status='ok', transaction_id=transaction_id,
                           versions=versions, idempotent=False)

    @app.post("/v1/json/read")
    def read_json():
        body = request.get_json(silent=True) or {}
        try:
            path = _safe_json_path(root, body.get("path"))
        except StorageServiceError as error:
            return jsonify(status="error", code=str(error)), 400
        with lock:
            if not path.exists():
                return jsonify(status="ok", exists=False, data=None, version=None)
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return jsonify(status="error", code="corrupt_json"), 503
            return jsonify(status="ok", exists=True, data=value, version=version_for(value))

    @app.post("/v1/json/read-batch")
    def read_json_batch():
        body = request.get_json(silent=True)
        raw_paths = body.get("paths") if isinstance(body, dict) else None
        if (not isinstance(raw_paths, list) or not 1 <= len(raw_paths) <= 16
                or len(set(map(str, raw_paths))) != len(raw_paths)):
            return jsonify(status="error", code="invalid_batch"), 400
        try:
            paths = [(str(raw), _safe_json_path(root, raw)) for raw in raw_paths]
        except StorageServiceError as error:
            return jsonify(status="error", code=str(error)), 400
        items = {}
        with lock:
            for relative, path in paths:
                if not path.exists():
                    items[relative] = {"exists": False, "data": None, "version": None}
                    continue
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    return jsonify(status="error", code="corrupt_json"), 503
                items[relative] = {
                    "exists": True,
                    "data": value,
                    "version": version_for(value),
                }
        return jsonify(status="ok", items=items)

    @app.post("/v1/json/write")
    def write_json():
        body = request.get_json(silent=True) or {}
        if "data" not in body:
            return jsonify(status="error", code="data_required"), 400
        try:
            path = _safe_json_path(root, body.get("path"))
        except StorageServiceError as error:
            return jsonify(status="error", code=str(error)), 400
        with lock:
            current = None
            if path.exists():
                try:
                    current = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    return jsonify(status="error", code="corrupt_json"), 503
            if "expected_version" in body:
                actual = version_for(current) if path.exists() else None
                if body.get("expected_version") != actual:
                    return jsonify(status="error", code="version_conflict"), 409
            if path.exists():
                _atomic_json(Path(str(path) + ".bak"), current)
            _atomic_json(path, body["data"])
            return jsonify(status="ok", version=version_for(body["data"]))

    @app.get("/v1/backups")
    def backup_list():
        with lock:
            return jsonify(status="ok", backups=list_backups(backups))

    @app.post("/v1/backups")
    def backup_create():
        with lock:
            try:
                path, manifest = create_backup(
                    root, backups, reason="manual", retention=backup_retention,
                )
            except StorageServiceError as error:
                return jsonify(status="error", code=str(error)), 503
            return jsonify(
                status="ok",
                name=path.name,
                sha256=_file_sha256(path),
                created_at=manifest["created_at"],
                file_count=len(manifest["files"]),
            )

    @app.get("/v1/backups/<name>")
    def backup_download(name):
        try:
            path = _backup_path(backups, name)
            inspect_backup(path)
        except StorageServiceError as error:
            status = 404 if str(error) == "backup_not_found" else 400
            return jsonify(status="error", code=str(error)), status
        return send_file(
            path,
            mimetype="application/zip",
            as_attachment=True,
            download_name=path.name,
            conditional=True,
        )

    @app.post("/v1/backups/<name>/restore")
    def backup_restore(name):
        body = request.get_json(silent=True) or {}
        expected_confirmation = "RESTORE " + name
        if body.get("apply") is not True or body.get("confirmation") != expected_confirmation:
            return jsonify(
                status="error",
                code="restore_confirmation_required",
                confirmation=expected_confirmation,
            ), 409
        with lock:
            try:
                path = _backup_path(backups, name)
                manifest, safety = restore_backup(
                    root, path, backups, retention=backup_retention,
                )
            except StorageServiceError as error:
                status = 404 if str(error) == "backup_not_found" else 400
                return jsonify(status="error", code=str(error)), status
            return jsonify(
                status="ok",
                restored=name,
                restored_created_at=manifest["created_at"],
                safety_backup=safety.name,
            )

    return app


def main():
    from waitress import create_server

    root = storage_root()
    token = os.getenv("TEMLI_STORAGE_TOKEN", "")
    initialize = os.getenv("TEMLI_STORAGE_INITIALIZE_EMPTY", "false").lower() == "true"
    backups = backup_root(root)
    retention = int(os.getenv("TEMLI_BACKUP_RETENTION", "30"))
    interval = int(os.getenv("TEMLI_BACKUP_INTERVAL_SECONDS", "21600"))
    if retention < 1 or retention > 1000:
        raise StorageServiceError("TEMLI_BACKUP_RETENTION must be between 1 and 1000")
    if interval != 0 and interval < 300:
        raise StorageServiceError("TEMLI_BACKUP_INTERVAL_SECONDS must be 0 or at least 300")
    app = create_app(
        root,
        token,
        initialize=initialize,
        backups=backups,
        backup_retention=retention,
    )
    lock = app.extensions["temli_storage_lock"]
    stop = None
    worker = None
    if interval:
        with lock:
            create_backup(root, backups, reason="startup", retention=retention)
        stop, worker = start_backup_worker(
            root, backups, lock, interval=interval, retention=retention,
        )
    server = create_server(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
        threads=4,
        max_request_body_size=MAX_REQUEST_BYTES,
        expose_tracebacks=False,
    )
    print("TEMLI Russian JSON storage: ready", flush=True)
    print("TEMLI storage: " + str(root), flush=True)
    print("TEMLI backups: " + str(backups), flush=True)
    try:
        server.run()
    finally:
        if stop is not None:
            stop.set()
        if worker is not None:
            worker.join(timeout=5)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Some BotHost nodes discard stderr when a container exits immediately.
        # Persist only the exception class and safe message; never environment
        # values or request data.
        try:
            diagnostic_root = Path(os.getenv("DATA_DIR", "/tmp")).resolve()
            diagnostic_root.mkdir(parents=True, exist_ok=True)
            _atomic_json(diagnostic_root / "temli-storage-startup-error.json", {
                "error_type": type(error).__name__,
                "message": str(error)[:500],
            })
        except Exception:
            pass
        raise
