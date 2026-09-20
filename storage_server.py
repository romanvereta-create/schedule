"""Russian-side JSON storage service for the TEMLI split deployment."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
import threading
from pathlib import Path, PurePosixPath

from flask import Flask, jsonify, request
from persistent_storage import READY_FILE


CORE_FILES = ("schedule.json", "students.json", "settings.json", "teacher_registry.json")
MAX_REQUEST_BYTES = 12 * 1024 * 1024


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
    raw = str(raw or "").replace("\\", "/").strip("/")
    part = PurePosixPath(raw)
    if (not raw or part.is_absolute() or ".." in part.parts or "." in part.parts
            or any(not item or len(item) > 128 for item in part.parts)
            or len(raw) > 512 or part.suffix.lower() != ".json"):
        raise StorageServiceError("invalid_path")
    path = (root / Path(*part.parts)).resolve()
    if not path.is_relative_to(root):
        raise StorageServiceError("invalid_path")
    return path


def create_app(root, token, *, initialize=False):
    root = Path(root).resolve()
    token = str(token or "")
    if len(token) < 32:
        raise StorageServiceError("TEMLI_STORAGE_TOKEN must contain at least 32 characters")
    if initialize and not (root / READY_FILE).exists():
        initialize_empty(root)
    validate_root(root)

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES
    lock = threading.RLock()

    @app.before_request
    def authenticate():
        if request.path == "/health":
            return None
        supplied = request.headers.get("Authorization", "")
        expected = "Bearer " + token
        if not hmac.compare_digest(supplied, expected):
            return jsonify(status="error", code="unauthorized"), 401
        if not request.is_json:
            return jsonify(status="error", code="json_required"), 415
        return None

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="temli-storage", schema=1)

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

    return app


def main():
    from waitress import create_server

    root = storage_root()
    token = os.getenv("TEMLI_STORAGE_TOKEN", "")
    initialize = os.getenv("TEMLI_STORAGE_INITIALIZE_EMPTY", "false").lower() == "true"
    app = create_app(root, token, initialize=initialize)
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
    server.run()


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
