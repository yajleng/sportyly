from __future__ import annotations
import time
from typing import Any, Dict, Optional, Tuple

class TTLCache:
    """Very small, process-local TTL cache. Safe for single-worker use."""
    def __init__(self, default_ttl: float = 30.0, max_items: int = 500):
        self._ttl = default_ttl
        self._max = max_items
        self._store: Dict[str, Tuple[float, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        item = self._store.get(key)
        if not item:
            return None
        exp, val = item
        if exp < time.time():
            self._store.pop(key, None)
            return None
        return val

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        if len(self._store) >= self._max:
            # drop oldest one (cheap sweep)
            oldest = min(self._store.items(), key=lambda p: p[1][0])[0]
            self._store.pop(oldest, None)
        self._store[key] = (time.time() + (ttl or self._ttl), value)

    def clear(self) -> None:
        self._store.clear()
