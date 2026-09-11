"""Short-lived, tenant-scoped undo for calendar changes; no financial operations."""
import copy
import secrets
import time


class CalendarUndo:
    def __init__(self, ttl=120, capacity=64):
        self.ttl = ttl
        self.capacity = capacity
        self.records = {}

    def remember(self, owner, before, after):
        # Caller holds the application's data lock through save and registration.
        now = time.monotonic()
        self.records = {key: value for key, value in self.records.items()
                        if value["expires"] > now and key != owner}
        changed = [key for key in before.keys() | after.keys()
                   if before.get(key) != after.get(key)]
        if not changed:
            return None
        token = secrets.token_urlsafe(24)
        self.records[owner] = {
            "token": token, "expires": now + self.ttl,
            "before": {key: copy.deepcopy(before.get(key)) for key in changed},
            "after": {key: copy.deepcopy(after.get(key)) for key in changed},
        }
        while len(self.records) > self.capacity:
            del self.records[next(iter(self.records))]
        return token

    def prepare(self, owner, token, current):
        record = self.records.get(owner)
        if not record or not isinstance(token, str) or not token.isascii() or not secrets.compare_digest(record["token"], token):
            raise ValueError("undo_unavailable")
        if record["expires"] <= time.monotonic():
            self.records.pop(owner, None)
            raise ValueError("undo_expired")
        if any(current.get(key) != value for key, value in record["after"].items()):
            raise ValueError("undo_conflict")
        restored_ids = {str(item.get("id")) for rows in record["before"].values()
                        for item in (rows or []) if item.get("id") is not None}
        if any(str(item.get("id")) in restored_ids
               for key, rows in current.items() if key not in record["before"]
               for item in rows):
            raise ValueError("undo_conflict")
        restored = copy.deepcopy(current)
        for key, value in record["before"].items():
            if value is None:
                restored.pop(key, None)
            else:
                restored[key] = copy.deepcopy(value)
        return restored

    def consume(self, owner, token):
        record = self.records.get(owner)
        if record and record["token"] == token:
            del self.records[owner]
