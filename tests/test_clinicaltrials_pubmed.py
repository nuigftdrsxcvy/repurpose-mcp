from __future__ import annotations

import httpx
import pytest

from repurpose_mcp import clinicaltrials, pubmed
from repurpose_mcp.http import ApiClient


async def test_existing_trials(api):
    res = await clinicaltrials.existing_trials(api, "sirolimus", "lymphangioleiomyomatosis")
    assert res.total_count >= len(res.trials) > 0
    milestone = next(t for t in res.trials if t.nct_id == "NCT00414648")  # MILES trial
    assert milestone.phases == ["PHASE3"]
    assert milestone.status == "COMPLETED"
    assert milestone.enrollment == 89 and milestone.enrollment_type == "ACTUAL"
    assert milestone.url == "https://clinicaltrials.gov/study/NCT00414648"


async def test_existing_trials_no_results(api):
    res = await clinicaltrials.existing_trials(api, "paracetamol", "lymphangioleiomyomatosis")
    assert res.total_count == 0 and res.trials == []


async def test_get_study_missing_returns_none(api):
    assert await clinicaltrials.get_study(api, "NCT09999999") is None


async def test_literature(api):
    res = await pubmed.literature(api, "sirolimus", "lymphangioleiomyomatosis", max_results=5)
    assert res.query == "(sirolimus) AND (lymphangioleiomyomatosis)"
    assert res.total_count > 100
    assert len(res.articles) == 5
    a = res.articles[0]
    assert a.pmid.isdigit() and a.title and a.year and a.year > 1990
    assert a.url == f"https://pubmed.ncbi.nlm.nih.gov/{a.pmid}/"
    assert "MeSH" in (res.query_translation or "")


async def test_fetch_records(api):
    recs = await pubmed.fetch_records(api, ["21410393", "99999999999"])
    assert set(recs) == {"21410393"}  # nonexistent PMIDs are simply absent
    assert "sirolimus" in recs["21410393"]["text"].lower()


async def test_literature_sends_api_key_from_env(monkeypatch):
    monkeypatch.setenv("NCBI_API_KEY", "secret-key")
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if "esearch" in req.url.path:
            return httpx.Response(200, json={"esearchresult": {"count": "1", "idlist": ["1"]}})
        return httpx.Response(200, json={"result": {"uids": ["1"], "1": {"title": "T", "pubdate": "2001 Jan"}}})

    async with ApiClient(transport=httpx.MockTransport(handler)) as c:
        res = await pubmed.literature(c, "a", "b")
        assert c._intervals[pubmed.NCBI_HOST] == 0.1  # faster limit allowed with a key
    assert all(r.url.params["api_key"] == "secret-key" for r in seen)
    assert res.articles[0].year == 2001


async def test_literature_requires_terms():
    with pytest.raises(ValueError):
        await pubmed.literature(None, " ", "x")  # type: ignore[arg-type]
