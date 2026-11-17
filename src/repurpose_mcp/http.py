"""Shared async HTTP client: timeouts, retries with backoff, per-host rate limiting and a TTL cache.

One `ApiClient` is meant to live for the lifetime of an event loop (the MCP server process, or one
eval run). Tests build their own instance with a replay transport.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import time
from collections import OrderedDict
from typing import Any
from urllib.parse import urlsplit

import httpx

from repurpose_mcp import __version__

log = logging.getLogger(__name__)

USER_AGENT = f"repurpose-mcp/{__version__} (drug repurposing evidence tool)"

# Minimum seconds between requests to each host. Chosen to stay well inside published guidance:
# NCBI allows 3 req/s without an API key (10 with one); ClinicalTrials.gov asks for ~50 req/min.
DEFAULT_MIN_INTERVAL: dict[str, float] = {
    "api.platform.opentargets.org": 0.2,
    "www.ebi.ac.uk": 0.2,
    "clinicaltrials.gov": 1.2,
    "eutils.ncbi.nlm.nih.gov": 0.34,
}
NCBI_INTERVAL_WITH_KEY = 0.1

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_RETRY_AFTER = 30.0


class UpstreamError(RuntimeError):
    """An upstream API failed or returned something unusable."""


class _HostLimiter:
    def __init__(self, interval: float) -> None:
        self.interval = interval
        self._lock = asyncio.Lock()
        self._next_slot = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if self._next_slot > now:
                await asyncio.sleep(self._next_slot - now)
                now = self._next_slot
            self._next_slot = now + self.interval


class _TTLCache:
    def __init__(self, maxsize: int, ttl: float) -> None:
        self.maxsize = maxsize
        self.ttl = ttl
        self._data: OrderedDict[str, tuple[float, str]] = OrderedDict()

    def get(self, key: str) -> str | None:
        item = self._data.get(key)
        if item is None:
            return None
        expires, value = item
        if expires < time.monotonic():
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return value

    def set(self, key: str, value: str) -> None:
        self._data[key] = (time.monotonic() + self.ttl, value)
        self._data.move_to_end(key)
        while len(self._data) > self.maxsize:
            self._data.popitem(last=False)


class ApiClient:
    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 30.0,
        max_attempts: int = 4,
        backoff_base: float = 0.5,
        cache_ttl: float = 6 * 3600,
        cache_size: int = 512,
        min_interval: dict[str, float] | None = None,
        rate_limit: bool = True,
    ) -> None:
        self._http = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(timeout, connect=10.0),
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base
        self.rate_limit = rate_limit
        self._intervals = dict(DEFAULT_MIN_INTERVAL if min_interval is None else min_interval)
        self._limiters: dict[str, _HostLimiter] = {}
        self._cache = _TTLCache(cache_size, cache_ttl)

    def set_host_interval(self, host: str, interval: float) -> None:
        self._intervals[host] = interval
        self._limiters.pop(host, None)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> ApiClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        return _parse_json(await self.request("GET", url, params=params), url)

    async def post_json(self, url: str, body: dict[str, Any]) -> Any:
        return _parse_json(await self.request("POST", url, json_body=body), url)

    async def get_text(self, url: str, params: dict[str, Any] | None = None) -> str:
        return await self.request("GET", url, params=params)

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        missing_statuses: tuple[int, ...] = (),
    ) -> str:
        """Return the response body as text. Statuses in missing_statuses (e.g. 404) mean "no such
        record" and return "" (cached like any other answer)."""
        params = {k: v for k, v in (params or {}).items() if v is not None}
        key = _cache_key(method, url, params, json_body)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        host = urlsplit(url).hostname or ""
        last_error: str = ""
        for attempt in range(1, self.max_attempts + 1):
            await self._throttle(host)
            try:
                resp = await self._http.request(method, url, params=params, json=json_body)
            except httpx.TransportError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                delay = self._backoff(attempt)
            else:
                if resp.status_code in missing_statuses:
                    self._cache.set(key, "")
                    return ""
                if resp.is_success:
                    self._cache.set(key, resp.text)
                    return resp.text
                last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
                if resp.status_code not in RETRY_STATUSES:
                    break
                delay = _retry_after(resp) or self._backoff(attempt)
            if attempt < self.max_attempts:
                log.warning("%s %s failed (%s); retry %d in %.1fs", method, url, last_error, attempt, delay)
                await asyncio.sleep(delay)
        raise UpstreamError(f"{method} {url} failed after {attempt} attempt(s): {last_error}")

    async def _throttle(self, host: str) -> None:
        if not self.rate_limit:
            return
        interval = self._intervals.get(host)
        if not interval:
            return
        limiter = self._limiters.get(host)
        if limiter is None:
            limiter = self._limiters[host] = _HostLimiter(interval)
        await limiter.wait()

    def _backoff(self, attempt: int) -> float:
        return self.backoff_base * (2 ** (attempt - 1)) + random.uniform(0, self.backoff_base)


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("Retry-After")
    if not value:
        return None
    try:
        return min(float(value), MAX_RETRY_AFTER)
    except ValueError:
        return None


def _cache_key(method: str, url: str, params: dict[str, Any], body: dict[str, Any] | None) -> str:
    raw = json.dumps([method, url, sorted((k, str(v)) for k, v in params.items()), body], sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def _parse_json(text: str, url: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise UpstreamError(f"{url} returned non-JSON content: {text[:200]!r}") from exc
