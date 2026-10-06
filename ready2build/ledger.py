import json
import os
from pathlib import Path
from threading import Lock


class Ledger:
    """Small atomic JSON ledger keyed by Jira issue and content fingerprint."""
    def __init__(self, path: Path):
        self.path = path
        self._lock = Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("{}", encoding="utf-8")

    def _read(self):
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def is_processed(self, key: str, fingerprint: str) -> bool:
        with self._lock:
            return self._read().get(key, {}).get("fingerprint") == fingerprint

    def record(self, key: str, fingerprint: str, correlation_id: str, **data):
        with self._lock:
            entries = self._read()
            entries[key] = {"fingerprint": fingerprint, "correlation_id": correlation_id, **data}
            temp = self.path.with_suffix(self.path.suffix + ".tmp")
            temp.write_text(json.dumps(entries, indent=2), encoding="utf-8")
            try:
                os.replace(temp, self.path)
            except PermissionError:
                # Some synchronized Windows folders deny rename replacement; retain the update.
                self.path.write_text(temp.read_text(encoding="utf-8"), encoding="utf-8")
                temp.unlink(missing_ok=True)

    def get(self, key: str):
        return self._read().get(key)
