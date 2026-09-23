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
import time
import uuid
import urllib.error
import urllib.request
from pathlib import PurePosixPath
from urllib.parse import quote, urlsplit


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
    def __init__(self, base_url, token, *, backup_read_token=None, timeout=20):
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
        backup_read_token = str(backup_read_token or token)
        if len(backup_read_token) < 32:
            raise RemoteStorageError(
                "TEMLI_STORAGE_BACKUP_READ_TOKEN must contain at least 32 characters")
        self.backup_read_token = backup_read_token
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

    def status(self):
        """Verify authenticated access without reading tenant data."""
        result = self._request("/v1/status", {})
        backup = result.get("backup")
        if not isinstance(backup, dict):
            raise RemoteStorageError("invalid_storage_response")
        return {
            "service": str(result.get("service", "")),
            "backup": backup,
        }

    def list_backups(self):
        """List verified server backups without exposing authentication details."""
        result = self._get_json("/v1/backups")
        backups = result.get("backups")
        if not isinstance(backups, list):
            raise RemoteStorageError("invalid_storage_response")
        return backups

    def download_backup(self, name, *, max_bytes=512 * 1024 * 1024):
        """Download one archive with a strict response-size ceiling."""
        name = str(name or "")
        if not name or "/" in name or "\\" in name or name in (".", ".."):
            raise RemoteStorageError("invalid_backup_name")
        req = urllib.request.Request(
            self.base_url + "/v1/backups/" + quote(name, safe=""),
            method="GET",
            headers={"Authorization": "Bearer " + self.backup_read_token,
                     "Accept": "application/zip"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout,
                                        context=ssl.create_default_context()) as response:
                declared = response.headers.get("Content-Length")
                if declared and int(declared) > max_bytes:
                    raise RemoteStorageError("storage_response_too_large")
                raw = response.read(max_bytes + 1)
        except RemoteStorageError:
            raise
        except urllib.error.HTTPError as error:
            error.close()
            raise RemoteStorageError("backup_download_failed") from None
        except (OSError, ValueError):
            raise RemoteStorageError("storage_unavailable") from None
        if len(raw) > max_bytes:
            raise RemoteStorageError("storage_response_too_large")
        return raw

    def _get_json(self, endpoint):
        req = urllib.request.Request(
            self.base_url + endpoint,
            method="GET",
            headers={"Authorization": "Bearer " + self.backup_read_token,
                     "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout,
                                        context=ssl.create_default_context()) as response:
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise RemoteStorageError("storage_response_too_large")
                result = json.loads(raw)
        except RemoteStorageError:
            raise
        except urllib.error.HTTPError as error:
            error.close()
            raise RemoteStorageError("remote_error") from None
        except (OSError, ValueError, json.JSONDecodeError):
            raise RemoteStorageError("storage_unavailable") from None
        if not isinstance(result, dict) or result.get("status") != "ok":
            raise RemoteStorageError("invalid_storage_response")
        return result

    def read_json_batch(self, defaults):
        """Read several JSON documents in one cross-region HTTP request."""
        if not isinstance(defaults, dict) or not 1 <= len(defaults) <= 16:
            raise RemoteStorageError("invalid_batch")
        cleaned = {_clean_relative_path(path): default for path, default in defaults.items()}
        result = self._request("/v1/json/read-batch", {"paths": list(cleaned)})
        items = result.get("items")
        if not isinstance(items, dict) or set(items) != set(cleaned):
            raise RemoteStorageError("invalid_storage_response")
        values = {}
        with self._lock:
            for path, default in cleaned.items():
                item = items.get(path)
                if not isinstance(item, dict):
                    raise RemoteStorageError("invalid_storage_response")
                self._versions[path] = item.get("version")
                values[path] = item.get("data") if item.get("exists") else default
        return values

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

    def has_cached_file_version(self, path):
        """Whether this process has an exact version for a local file copy."""
        path = _clean_relative_path(path)
        with self._lock:
            return path in self._file_versions and self._file_versions[path] is not None

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

    def commit_payment_transaction(self, json_files, binary_files=None, *, transaction_id=None):
        """Atomically commit payment-related JSON and XLSX files on the server."""
        binary_files = {} if binary_files is None else binary_files
        transaction_id = transaction_id or ('payment-' + uuid.uuid4().hex)
        items = []
        with self._lock:
            for raw_path, data in json_files.items():
                path = _clean_relative_path(raw_path)
                if path not in self._versions:
                    raise RemoteStorageError('read_json_before_transaction')
                items.append({
                    'path': path, 'kind': 'json', 'data': data,
                    'expected_version': self._versions[path],
                })
            for raw_path, raw in binary_files.items():
                path = _clean_relative_path(raw_path)
                if path not in self._file_versions:
                    raise RemoteStorageError('read_file_before_transaction')
                if not isinstance(raw, bytes) or not raw or len(raw) > 8 * 1024 * 1024:
                    raise RemoteStorageError('invalid_file_size')
                items.append({
                    'path': path, 'kind': 'binary',
                    'data': base64.b64encode(raw).decode('ascii'),
                    'expected_version': self._file_versions[path],
                })
        payload = {'transaction_id': transaction_id, 'items': items}
        result = None
        for attempt in range(3):
            try:
                result = self._request('/v1/transactions/payment', payload)
                break
            except RemoteStorageError as exc:
                if isinstance(exc, RemoteStorageConflict) or str(exc) != 'storage_unavailable' or attempt == 2:
                    raise
                time.sleep(0.2 * (attempt + 1))
        versions = result.get('versions') if isinstance(result, dict) else None
        if not isinstance(versions, dict):
            raise RemoteStorageError('invalid_storage_response')
        with self._lock:
            for raw_path in json_files:
                path = _clean_relative_path(raw_path)
                if versions.get(path) != version_for_client(json_files[raw_path]):
                    raise RemoteStorageError('transaction_checksum_mismatch')
                self._versions[path] = versions[path]
            for raw_path, raw in binary_files.items():
                path = _clean_relative_path(raw_path)
                if versions.get(path) != hashlib.sha256(raw).hexdigest():
                    raise RemoteStorageError('transaction_checksum_mismatch')
                self._file_versions[path] = versions[path]
        return transaction_id


def version_for_client(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def configured_remote_storage(environ=None):
    environ = os.environ if environ is None else environ
    url = str(environ.get("TEMLI_STORAGE_URL", "") or "").strip()
    legacy = str(environ.get("TEMLI_STORAGE_TOKEN", "") or "")
    token = str(environ.get("TEMLI_STORAGE_APP_TOKEN", "") or legacy)
    backup_read_token = str(
        environ.get("TEMLI_STORAGE_BACKUP_READ_TOKEN", "") or legacy)
    if not url and not token:
        return None
    if not url or not token:
        raise RemoteStorageError(
            "TEMLI_STORAGE_URL and TEMLI_STORAGE_APP_TOKEN must be set together")
    if not backup_read_token:
        raise RemoteStorageError(
            "TEMLI_STORAGE_BACKUP_READ_TOKEN is required with scoped storage credentials")
    return RemoteJsonStorage(url, token, backup_read_token=backup_read_token)
