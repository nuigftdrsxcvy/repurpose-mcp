"""ClinicalTrials.gov API v2."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

from repurpose_mcp.http import ApiClient
from repurpose_mcp.models import Trial, TrialsResult

STUDIES_URL = "https://clinicaltrials.gov/api/v2/studies"
STUDY_PAGE_URL = "https://clinicaltrials.gov/study"
FIELDS = "NCTId,BriefTitle,Phase,OverallStatus,EnrollmentCount,EnrollmentType,StartDate"


async def existing_trials(client: ApiClient, drug: str, disease: str, max_results: int = 25) -> TrialsResult:
    drug, disease = drug.strip(), disease.strip()
    if not drug or not disease:
        raise ValueError("Both drug and disease are required.")
    params = {
        "query.cond": disease,
        "query.intr": drug,
        "fields": FIELDS,
        "pageSize": max_results,
        "countTotal": "true",
    }
    data = await client.get_json(STUDIES_URL, params)
    trials = [_trial(s["protocolSection"]) for s in data.get("studies", [])]
    return TrialsResult(
        drug=drug,
        disease=disease,
        total_count=data.get("totalCount", len(trials)),
        trials=trials,
        query_url=f"https://clinicaltrials.gov/search?{urlencode({'cond': disease, 'intr': drug})}",
    )


async def get_study(client: ApiClient, nct_id: str) -> dict[str, Any] | None:
    """Full study record, or None if the NCT id does not exist (404) or is malformed (400)."""
    text = await client.request(
        "GET", f"{STUDIES_URL}/{nct_id}", params={"format": "json"}, missing_statuses=(400, 404)
    )
    return json.loads(text) if text else None


def _trial(p: dict[str, Any]) -> Trial:
    ident = p.get("identificationModule", {})
    status = p.get("statusModule", {})
    design = p.get("designModule", {})
    enrol = design.get("enrollmentInfo", {})
    nct = ident["nctId"]
    return Trial(
        nct_id=nct,
        title=ident.get("briefTitle", ""),
        phases=design.get("phases", []),
        status=status.get("overallStatus"),
        enrollment=enrol.get("count"),
        enrollment_type=enrol.get("type"),
        start_date=(status.get("startDateStruct") or {}).get("date"),
        url=f"{STUDY_PAGE_URL}/{nct}",
    )
