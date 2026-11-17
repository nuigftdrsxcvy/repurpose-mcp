from __future__ import annotations

import asyncio

import httpx
import pytest

from repurpose_mcp import http as http_mod
from repurpose_mcp.http import ApiClient, UpstreamError


def client_with(handler, **kw) -> ApiClient:
    return ApiClient(transport=httpx.MockTransport(handler), backoff_base=0, **kw)


async def test_retries_on_503_then_succeeds():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json={"ok": True})

    async with client_with(handler) as c:
        assert await c.get_json("https://example.org/x") == {"ok": True}
    assert len(calls) == 3


async def test_retries_on_transport_error():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if len(calls) == 1:
            raise httpx.ReadTimeout("slow", request=req)
        return httpx.Response(200, json=[1])

    async with client_with(handler) as c:
        assert await c.get_json("https://example.org/x") == [1]


async def test_gives_up_after_max_attempts():
    async with client_with(lambda r: httpx.Response(502), max_attempts=2) as c:
        with pytest.raises(UpstreamError, match="after 2 attempt"):
            await c.get_json("https://example.org/x")


async def test_does_not_retry_client_errors():
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(400, text="bad query")

    async with client_with(handler) as c:
        with pytest.raises(UpstreamError, match="HTTP 400: bad query"):
            await c.get_json("https://example.org/x")
    assert len(calls) == 1


async def test_honours_retry_after(monkeypatch):
    sleeps = []
    real_sleep = asyncio.sleep

    async def fake_sleep(s):
        sleeps.append(s)
        await real_sleep(0)

    monkeypatch.setattr(http_mod.asyncio, "sleep", fake_sleep)
    responses = iter([httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, json={})])
    async with client_with(lambda r: next(responses), rate_limit=False) as c:
        await c.get_json("https://example.org/x")
    assert sleeps == [7.0]


async def test_cache_avoids_repeat_requests():
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(200, json={"n": len(calls)})

    async with client_with(handler) as c:
        a = await c.post_json("https://example.org/g", {"query": "q", "variables": {"a": 1}})
        b = await c.post_json("https://example.org/g", {"query": "q", "variables": {"a": 1}})
        other = await c.post_json("https://example.org/g", {"query": "q", "variables": {"a": 2}})
    assert a == b == {"n": 1} and other == {"n": 2}


async def test_missing_status_returns_empty():
    async with client_with(lambda r: httpx.Response(404)) as c:
        assert await c.request("GET", "https://example.org/missing", missing_statuses=(404,)) == ""


async def test_rate_limiter_spaces_requests(monkeypatch):
    sleeps = []
    real_sleep = asyncio.sleep

    async def fake_sleep(s):
        sleeps.append(s)
        await real_sleep(0)

    monkeypatch.setattr(http_mod.asyncio, "sleep", fake_sleep)
    async with client_with(lambda r: httpx.Response(200, json={}), min_interval={"example.org": 0.5}) as c:
        for i in range(3):
            await c.get_json("https://example.org/x", {"i": i})
    # first request goes straight through; the next two are booked one interval apart. (The fake
    # sleep does not advance the clock, so the second wait is measured from the same start.)
    assert len(sleeps) == 2
    assert 0.3 < sleeps[0] <= 0.5 and 0.8 < sleeps[1] <= 1.0


async def test_non_json_raises_upstream_error():
    async with client_with(lambda r: httpx.Response(200, text="<html>")) as c:
        with pytest.raises(UpstreamError, match="non-JSON"):
            await c.get_json("https://example.org/x")
