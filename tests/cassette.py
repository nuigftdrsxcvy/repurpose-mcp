"""Minimal record/replay transport for httpx.

Replay (default): requests are answered from tests/cassettes/<name>.json and anything unrecorded
fails loudly. Record (REPURPOSE_RECORD=1): requests go to the real APIs and successful responses
are saved. Credentials (api_key, email) are never part of the key or the stored URL.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

import httpx

SCRUB_PARAMS = {"api_key", "email"}


def request_key(request: httpx.Request) -> str:
    params = sorted((k, v) for k, v in parse_qsl(request.url.query.decode()) if k not in SCRUB_PARAMS)
    body = request.content or b""
    digest = hashlib.sha256(body).hexdigest()[:16] if body else "-"
    return f"{request.method} {request.url.host}{request.url.path}?{urlencode(params)} {digest}"


class Cassette(httpx.AsyncBaseTransport):
    def __init__(self, path: Path, record: bool) -> None:
        self.path = path
        self.record = record
        self.entries: dict[str, dict] = {}
        if path.exists():
            self.entries = json.loads(path.read_text(encoding="utf-8"))
        self._real = httpx.AsyncHTTPTransport() if record else None
        self.dirty = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        key = request_key(request)
        if self.record:
            assert self._real is not None
            resp = await self._real.handle_async_request(request)
            body = await resp.aread()
            if resp.status_code < 400 or resp.status_code == 404:
                self.entries[key] = {
                    "status": resp.status_code,
                    "content_type": resp.headers.get("content-type", ""),
                    "body": body.decode("utf-8"),
                }
                self.dirty = True
            # body is already decoded, so drop content-encoding/length from the original headers
            headers = {"content-type": resp.headers.get("content-type", "")}
            return httpx.Response(resp.status_code, headers=headers, content=body, request=request)
        entry = self.entries.get(key)
        if entry is None:
            raise AssertionError(
                f"Request not in cassette {self.path.name}: {key}\n"
                "Re-record with: REPURPOSE_RECORD=1 uv run pytest"
            )
        return httpx.Response(
            entry["status"],
            headers={"content-type": entry["content_type"]},
            content=entry["body"].encode("utf-8"),
            request=request,
        )

    def save(self) -> None:
        if self.record and self.dirty:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.entries, indent=1, sort_keys=True), encoding="utf-8")

    async def aclose(self) -> None:
        if self._real:
            await self._real.aclose()
