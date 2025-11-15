from __future__ import annotations
import json
import time
from typing import Any, Mapping, Optional
import httpx

DEFAULT_TIMEOUT = 20.0

class HttpRetryingClient:
    """httpx client with basic retries/backoff + helper for GET with caching hook."""
    def __init__(self, headers: Optional[Mapping[str, str]] = None, timeout: float = DEFAULT_TIMEOUT):
        self._http = httpx.Client(timeout=timeout, headers=headers or {})

    def close(self) -> None:
        self._http.close()

    def get(self, url: str, *, params: Optional[Mapping[str, Any]] = None,
            retries: int = 2, backoff: float = 0.75) -> httpx.Response:
        last_exc = None
        for i in range(retries + 1):
            try:
                r = self._http.get(url, params=params or {})
                if r.status_code in (429, 502, 503, 504):
                    # retryable server / rate limit
                    raise httpx.HTTPStatusError("retryable", request=r.request, response=r)
                r.raise_for_status()
                return r
            except httpx.HTTPError as e:
                last_exc = e
                if i == retries:
                    break
                time.sleep(backoff * (2 ** i))
        assert last_exc is not None
        raise last_exc

    @staticmethod
    def cache_key(url: str, params: Optional[Mapping[str, Any]]) -> str:
        return f"{url}?{json.dumps(params or {}, sort_keys=True, separators=(',',':'))}"
