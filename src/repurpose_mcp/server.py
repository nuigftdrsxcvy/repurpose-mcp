"""repurpose-mcp: MCP server for finding approved, likely off-patent drugs with a plausible mechanism
for a (rare) disease, with every claim traceable to a source identifier."""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from typing import Annotated, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from repurpose_mcp import clinicaltrials, opentargets, pubmed
from repurpose_mcp.http import ApiClient, UpstreamError
from repurpose_mcp.models import (
    ApprovedDrugsResult,
    DiseaseTargetsResult,
    FindDiseaseResult,
    LiteratureResult,
    TrialsResult,
)

INSTRUCTIONS = """\
Tools for evidence-traceable drug repurposing research. Typical flow: find_disease ->
disease_targets -> approved_drugs_for_targets -> existing_trials and literature per candidate.
Every claim you make must cite an identifier returned by these tools (Open Targets disease/target
ID, ChEMBL ID, NCT ID or PMID). Association scores are not efficacy evidence; likely_off_patent is a
heuristic; nothing here is clinical advice."""

mcp = MCPServer(name="repurpose-mcp", instructions=INSTRUCTIONS)
READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True, idempotent_hint=True)

_client: ApiClient | None = None
T = TypeVar("T")


def client() -> ApiClient:
    global _client
    if _client is None:
        _client = ApiClient()
    return _client


async def _run(call: Awaitable[T]) -> T:
    """Surface bad input and upstream failures to the model as readable tool errors."""
    try:
        return await call
    except (ValueError, UpstreamError) as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool(annotations=READ_ONLY)
async def find_disease(
    name: Annotated[str, Field(description="Disease name, e.g. 'lymphangioleiomyomatosis'")],
    limit: Annotated[int, Field(ge=1, le=20, description="Maximum matches to return")] = 5,
) -> FindDiseaseResult:
    """Search Open Targets for a disease and return candidate disease IDs (MONDO/EFO/Orphanet) and
    names, best match first. Confirm the right one before using its ID."""
    return await _run(opentargets.find_disease(client(), name, limit))


@mcp.tool(annotations=READ_ONLY)
async def disease_targets(
    disease_id: Annotated[str, Field(description="Open Targets disease ID from find_disease, e.g. MONDO_0011705")],
    limit: Annotated[int, Field(ge=1, le=100)] = 20,
) -> DiseaseTargetsResult:
    """Top targets associated with a disease in Open Targets, with the overall association score and
    a score per evidence datatype (genetic_association, somatic_mutation, literature, animal_model,
    clinical, ...). Scores measure strength of target-disease evidence, NOT drug efficacy."""
    return await _run(opentargets.disease_targets(client(), disease_id, limit))


@mcp.tool(annotations=READ_ONLY)
async def approved_drugs_for_targets(
    target_ids: Annotated[
        list[str],
        Field(min_length=1, max_length=50, description="Ensembl gene IDs from disease_targets, in score order"),
    ],
    max_drugs: Annotated[int, Field(ge=1, le=200)] = 50,
) -> ApprovedDrugsResult:
    """Approved drugs (Open Targets maximum clinical stage = APPROVAL, i.e. phase 4) acting on the
    given targets: name, ChEMBL ID, mechanism of action, first approval year (ChEMBL), approved
    indications, and likely_off_patent (HEURISTIC: first approval >= 20 years ago; not a patent
    search). Drugs are ordered by the earliest-listed target they act on, so pass target IDs in
    the order disease_targets returned them. Salt forms are merged into the parent molecule."""
    return await _run(opentargets.approved_drugs_for_targets(client(), target_ids, max_drugs))


@mcp.tool(annotations=READ_ONLY)
async def existing_trials(
    drug: Annotated[str, Field(description="Drug name, e.g. 'sirolimus'")],
    disease: Annotated[str, Field(description="Disease name, e.g. 'lymphangioleiomyomatosis'")],
    max_results: Annotated[int, Field(ge=1, le=100)] = 25,
) -> TrialsResult:
    """ClinicalTrials.gov studies matching this drug (intervention) and disease (condition): NCT ID,
    title, phase, overall status, enrolment (actual or estimated)."""
    return await _run(clinicaltrials.existing_trials(client(), drug, disease, max_results))


@mcp.tool(annotations=READ_ONLY)
async def literature(
    drug: Annotated[str, Field(description="Drug name")],
    disease: Annotated[str, Field(description="Disease name")],
    max: Annotated[int, Field(ge=1, le=100, description="Maximum articles to return")] = 10,
) -> LiteratureResult:
    """PubMed articles mentioning both the drug and the disease (relevance order): PMID, title, year,
    journal, plus the total hit count and PubMed's query translation."""
    return await _run(pubmed.literature(client(), drug, disease, max))


BRIEF_PROMPT = """\
Produce a drug repurposing evidence brief for: **{disease}**

Audience: rare disease clinicians and trial teams. Purpose: shortlist approved, likely off-patent
drugs with a plausible mechanism, each traceable to sources. This is hypothesis generation, not
clinical advice.

## Procedure (use the repurpose-mcp tools; do not rely on memory for any fact in the brief)
1. `find_disease("{disease}")`. Pick the best match and state its ID. If the match is ambiguous,
   name the alternatives and say which you used.
2. `disease_targets(disease_id, limit=20)`.
3. `approved_drugs_for_targets` with all returned target IDs.
4. Shortlist up to 10 drugs. Order by the highest association score among the drug's targets;
   among similar scores prefer `likely_off_patent = true`. Drugs already approved for this disease
   (its ID is in `approved_indications`) go in a separate "Already approved for this disease" list,
   not in the table.
5. For each shortlisted drug call `existing_trials(drug, disease)` and `literature(drug, disease)`.
   Read the returned titles: only cite a trial or article if its title shows it concerns this drug
   (or class) in this disease. Do not cite records you have not retrieved.

## Output
A short header: disease name and ID, date, Open Targets data version.

Then one markdown table with exactly these columns:

| Drug | Target | Mechanism | Approval year | Off-patent heuristic | Trials | PMIDs | Evidence strength | Gaps |

- Drug: name and ChEMBL ID, e.g. `SIROLIMUS (CHEMBL413)`.
- Target: symbol, Ensembl ID and association score, e.g. `FKBP1A (ENSG00000088832, 0.53)`.
- Mechanism: as returned (mechanism of action + action type).
- Approval year: `year_of_first_approval` and its source; "unknown" if null.
- Off-patent heuristic: "likely (heuristic)", "unlikely (heuristic)" or "unknown". Never write
  "off-patent" as a fact.
- Trials: relevant NCT IDs with phase/status/enrolment, e.g. `NCT00414648 (Ph3, completed, n=89)`;
  "none found" if none.
- PMIDs: relevant PMIDs, e.g. `PMID:21410393`; "none found" if none.
- Evidence strength, using only retrieved records:
  - **Strong**: completed phase 2/3 trial in this disease and supporting publication(s).
  - **Moderate**: any interventional trial in this disease, or several case series/reports.
  - **Weak**: one or two publications, or only indirect (related-disease) evidence.
  - **Mechanistic only**: target association with no trial or publication found.
  - Downgrade one level when the best evidence is a pilot, single-arm or <20-participant study,
    and say so in Gaps.
- Gaps: what is missing or uncertain (no human data, small n, terminated trial, safety signal,
  withdrawn flag, paediatric data, ambiguous search hits, etc.).

After the table:
- "Already approved for this disease" (with IDs), if any.
- "Notable exclusions": drugs you dropped and why (e.g. withdrawn, unrelated hits).
- Limitations, verbatim in substance: association scores are not efficacy evidence; the off-patent
  flag is a heuristic based on approval year (verify in the Orange/Purple Book or equivalent);
  searches can miss evidence and can return irrelevant records; this is not clinical advice.

## Rules
- No claim without an ID. Every factual statement must carry the Open Targets, ChEMBL, NCT or PMID
  identifier it came from. If you cannot cite it, leave it out or write "none found".
- Never invent or "recall" identifiers. Only use IDs returned by the tools in this session.
- Do not describe a drug as effective, recommended or safe for this disease.
"""


@mcp.prompt(title="Repurposing evidence brief")
def repurposing_brief(
    disease: Annotated[str, Field(description="Disease name, e.g. 'lymphangioleiomyomatosis'")],
) -> str:
    """Build a sourced markdown evidence table of approved, likely off-patent repurposing candidates
    for a disease."""
    return BRIEF_PROMPT.format(disease=disease.strip())


def main() -> None:
    logging.basicConfig(level=logging.WARNING)  # stderr; stdout is the MCP stdio channel
    logging.getLogger("httpx").setLevel(logging.WARNING)
    mcp.run()


if __name__ == "__main__":
    main()
