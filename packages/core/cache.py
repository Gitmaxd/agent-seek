"""Simple filesystem JSON cache with TTL."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any


class FileCache:
    def __init__(self, root: str | Path, ttl_sec: int = 1800):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.ttl_sec = ttl_sec

    def _path(self, key: str) -> Path:
        h = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.root / f"{h}.json"

    def get(self, key: str) -> Any | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - data.get("_ts", 0) > self.ttl_sec:
                path.unlink(missing_ok=True)
                return None
            return data.get("value")
        except Exception:
            return None

    def set(self, key: str, value: Any) -> None:
        path = self._path(key)
        payload = {"_ts": time.time(), "value": value}
        path.write_text(json.dumps(payload), encoding="utf-8")
