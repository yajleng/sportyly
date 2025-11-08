
import time
from typing import Any, Callable, Dict, Tuple

class TTLCache:
    def __init__(self, ttl_seconds: int = 120):
        self.ttl = ttl_seconds
        self._store: Dict[Tuple[str, Tuple, Tuple], Tuple[float, Any]] = {}

    def cached(self, fn: Callable):
        def wrapper(*args, **kwargs):
            key = (fn.__name__, args, tuple(sorted(kwargs.items())))
            now = time.time()
            if key in self._store:
                ts, val = self._store[key]
                if now - ts < self.ttl:
                    return val
            val = fn(*args, **kwargs)
            self._store[key] = (now, val)
            return val
        return wrapper
