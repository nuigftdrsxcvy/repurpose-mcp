from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import pytest

from repurpose_mcp.http import ApiClient
from tests.cassette import Cassette

RECORD = os.environ.get("REPURPOSE_RECORD") == "1"
CASSETTES = Path(__file__).parent / "cassettes"

# Recorded responses are frozen in time; pin "today" so off-patent arithmetic stays stable.
TODAY = dt.date(2026, 11, 17)


@pytest.fixture
async def api(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    """ApiClient backed by a per-test cassette (tests/cassettes/<module>__<test>.json)."""
    if not RECORD:
        # Never let a local key change request shapes or leak into replays.
        monkeypatch.delenv("NCBI_API_KEY", raising=False)
        monkeypatch.delenv("NCBI_EMAIL", raising=False)
    name = f"{request.module.__name__.split('.')[-1]}__{request.node.name}"
    cassette = Cassette(CASSETTES / f"{name}.json", record=RECORD)
    client = ApiClient(transport=cassette, rate_limit=RECORD, backoff_base=0.5 if RECORD else 0)
    try:
        yield client
    finally:
        await client.aclose()
        cassette.save()
