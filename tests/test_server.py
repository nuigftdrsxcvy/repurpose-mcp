from __future__ import annotations

import pytest
from mcp import Client

from repurpose_mcp import server

EXPECTED_TOOLS = {"find_disease", "disease_targets", "approved_drugs_for_targets", "existing_trials", "literature"}


@pytest.fixture
def use_api(api, monkeypatch):
    # The MCP Client is opened inside each test (not a yield fixture): anyio cancel scopes must
    # be exited by the task that entered them.
    monkeypatch.setattr(server, "_client", api)


async def test_tools_and_prompt_are_registered(use_api):
    async with Client(server.mcp) as c:
        tools = (await c.list_tools()).tools
        prompts = (await c.list_prompts()).prompts
    assert {t.name for t in tools} == EXPECTED_TOOLS
    for t in tools:
        assert t.output_schema, f"{t.name} should return structured output"
        assert t.annotations and t.annotations.read_only_hint
    lit = next(t for t in tools if t.name == "literature")
    assert "max" in lit.input_schema["properties"]
    assert [p.name for p in prompts] == ["repurposing_brief"]


async def test_prompt_renders(use_api):
    async with Client(server.mcp) as c:
        res = await c.get_prompt("repurposing_brief", {"disease": "Castleman disease"})
    text = res.messages[0].content.text
    assert "Castleman disease" in text
    assert "| Drug | Target | Mechanism | Approval year | Off-patent heuristic | Trials | PMIDs |" in text
    assert "No claim without an ID" in text


async def test_tool_call_returns_structured_content(use_api):
    async with Client(server.mcp) as c:
        res = await c.call_tool("find_disease", {"name": "lymphangioleiomyomatosis", "limit": 3})
    assert not res.is_error
    assert res.structured_content["hits"][0]["id"] == "MONDO_0011705"


async def test_bad_input_is_a_readable_tool_error(use_api):
    async with Client(server.mcp) as c:
        res = await c.call_tool("disease_targets", {"disease_id": "lymphangioleiomyomatosis"})
    assert res.is_error
    assert "find_disease" in res.content[0].text


async def test_schema_validation(use_api):
    async with Client(server.mcp) as c:
        res = await c.call_tool("approved_drugs_for_targets", {"target_ids": []})
    assert res.is_error
