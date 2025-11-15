# app/services/cache.py
from __future__ import annotations

import time
from typing import Any, Callable, Tuple, Dict

class TTLCache:
    def __init__(self, ttl_seconds: int = 120, maxsize: int = 512):
        self.ttl = ttl_seconds
        self.maxsize = maxsize
        self._data: Dict[Tuple[Any, ...], Tuple[float, Any]] = {}

    def get(self, key: Tuple[Any, ...]):
        now = time.time()
        v = self._data.get(key)
        if not v:
            return None
        ts, val = v
        if now - ts > self.ttl:
            self._data.pop(key, None)
            return None
        return val

    def set(self, key: Tuple[Any, ...], value: Any):
        if len(self._data) >= self.maxsize:
            # naive eviction: clear all
            self._data.clear()
        self._data[key] = (time.time(), value)

cache = TTLCache()
