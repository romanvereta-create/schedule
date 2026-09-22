"""Authenticated client for the TEMLI JSON storage service.

The client is deliberately small and synchronous. TEMLI already serializes
read/modify/write operations with DATA_LOCK, so a blocking request preserves
the same semantics as the local filesystem implementation.
"""
from __future__ import annotations

import json
import base64
import hashlib
import os
import ssl
import threading
import urllib.error
import urllib.request
from pathlib import PurePosixPath
from urllib.parse import urlsplit


class RemoteStorageError(RuntimeError):
    pass


class RemoteStorageConflict(RemoteStorageError):
    pass


def _clean_relative_path(value):
    value = str(value or "").replace("\\", "/").strip("/")
    part = PurePosixPath(value)
    if (not value or part.is_absolute() or ".." in part.parts or "." in part.parts
            or any(not item or len(item) > 128 for item in part.parts)
            or len(value) > 512):
        raise RemoteStorageError("invalid_path")
    return part.as_posix()


class RemoteJsonStorage:
    def __init__(self, base_url, token, *, timeout=20):
        parsed = urlsplit(str(base_url or "").strip().rstrip("/"))
        allow_http = os.getenv("TEMLI_STORAGE_ALLOW_HTTP", "false").lower() == "true"
        if parsed.scheme not in ({"https", "http"} if allow_http else {"https"}):
            raise RemoteStorageError("TEMLI_STORAGE_URL must use HTTPS")
        if not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise RemoteStorageError("invalid TEMLI_STORAGE_URL")
        token = str(token or "")
        if len(token) < 32:
            raise RemoteStorageError("TEMLI_STORAGE_TOKEN must contain at least 32 characters")
        self.base_url = parsed.geturl().rstrip("/")
        self.token = token
        self.timeout = timeout
        self._versions = {}
        self._file_versions = {}
        self._lock = threading.RLock()

    def _request(self, endpoint, payload):
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + endpoint,
            data=raw,
            method="POST",
            headers={
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=ssl.create_default_context()) as response:
                raw_response = response.read(12 * 1024 * 1024 + 1)
                if len(raw_response) > 12 * 1024 * 1024:
                    raise RemoteStorageError('storage_response_too_large')
                result = json.loads(raw_response)
        except urllib.error.HTTPError as error:
            try:
                body = json.loads(error.read())
                code = str(body.get("code", "remote_error"))
            except Exception:
                code = "remote_error"
            finally:
                error.close()
            if error.code == 409:
                raise RemoteStorageConflict(code) from None
            raise RemoteStorageError(code) from None
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise RemoteStorageError("storage_unavailable") from error
        if not isinstance(result, dict) or result.get("status") != "ok":
            raise RemoteStorageError("invalid_storage_response")
        return result

    def read_json(self, path, default):
        path = _clean_relative_path(path)
        result = self._request("/v1/json/read", {"path": path})
        with self._lock:
            self._versions[path] = result.get("version")
        return result.get("data") if result.get("exists") else default

    def write_json(self, path, data):
        path = _clean_relative_path(path)
        with self._lock:
            known = path in self._versions
            version = self._versions.get(path)
        payload = {"path": path, "data": data}
        if known:
            payload["expected_version"] = version
        result = self._request("/v1/json/write", payload)
        with self._lock:
            self._versions[path] = result.get("version")

    def exists(self, path):
        path = _clean_relative_path(path)
        result = self._request("/v1/json/read", {"path": path})
        with self._lock:
            self._versions[path] = result.get("version")
        return bool(result.get("exists"))

    def read_file(self, path):
        """Return verified bytes or None. Files are not cached on local disk."""
        path = _clean_relative_path(path)
        result = self._request('/v1/files/read', {'path': path})
        raw = None
        if result.get('exists'):
            try:
                raw = base64.b64decode(result['data'], validate=True)
            except (KeyError, ValueError, TypeError):
                raise RemoteStorageError('invalid_file_response') from None
            if hashlib.sha256(raw).hexdigest() != result.get('version'):
                raise RemoteStorageError('file_checksum_mismatch')
        with self._lock:
            self._file_versions[path] = result.get('version')
        return raw

    def write_file(self, path, raw):
        """Conditional replacement; callers must read a file before editing it."""
        path = _clean_relative_path(path)
        if not isinstance(raw, bytes) or not raw or len(raw) > 8 * 1024 * 1024:
            raise RemoteStorageError('invalid_file_size')
        with self._lock:
            if path not in self._file_versions:
                raise RemoteStorageError('read_file_before_write')
            expected = self._file_versions[path]
        result = self._request('/v1/files/write', {
            'path': path,
            'data': base64.b64encode(raw).decode('ascii'),
            'expected_version': expected,
        })
        if result.get('version') != hashlib.sha256(raw).hexdigest():
            raise RemoteStorageError('file_checksum_mismatch')
        with self._lock:
            self._file_versions[path] = result['version']

    def delete_file(self, path):
        """Conditionally delete a file after it has been read."""
        path = _clean_relative_path(path)
        with self._lock:
            if path not in self._file_versions:
                raise RemoteStorageError('read_file_before_delete')
            expected = self._file_versions[path]
        result = self._request('/v1/files/delete', {
            'path': path,
            'expected_version': expected,
        })
        with self._lock:
            self._file_versions[path] = None
        return bool(result.get('existed'))


def configured_remote_storage(environ=None):
    environ = os.environ if environ is None else environ
    url = str(environ.get("TEMLI_STORAGE_URL", "") or "").strip()
    token = str(environ.get("TEMLI_STORAGE_TOKEN", "") or "")
    if not url and not token:
        return None
    if not url or not token:
        raise RemoteStorageError("TEMLI_STORAGE_URL and TEMLI_STORAGE_TOKEN must be set together")
    return RemoteJsonStorage(url, token)
