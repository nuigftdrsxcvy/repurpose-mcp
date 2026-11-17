"""Open Targets Platform GraphQL (schema checked against API v26.9).

Note: the old `Target.knownDrugs` / `Drug.yearOfFirstApproval` fields were removed upstream. Drugs
now come from `Target.drugAndClinicalCandidates`, approval status from `Drug.maximumClinicalStage`
("APPROVAL"), and first-approval year from ChEMBL (see chembl.py).
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable
from typing import Any

from repurpose_mcp import chembl
from repurpose_mcp.http import ApiClient, UpstreamError
from repurpose_mcp.models import (
    OFF_PATENT_HEURISTIC,
    ApprovedDrug,
    ApprovedDrugsResult,
    DiseaseHit,
    DiseaseTargetsResult,
    FindDiseaseResult,
    Indication,
    Mechanism,
    TargetAssociation,
)

GRAPHQL_URL = "https://api.platform.opentargets.org/api/v4/graphql"
PLATFORM_URL = "https://platform.opentargets.org"

OFF_PATENT_YEARS = 20
CLINICAL_DATASOURCE = "clinical_precedence"
MAX_TARGETS_PER_CALL = 50
_CHUNK = 25

ENSEMBL_RE = re.compile(r"^ENSG\d{11}$")
DISEASE_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9]+$")

_SEARCH_QUERY = """
query FindDisease($q: String!, $size: Int!) {
  search(queryString: $q, entityNames: ["disease"], page: {index: 0, size: $size}) {
    hits { id name entity description }
  }
}"""

_ASSOC_QUERY = """
query DiseaseTargets($id: String!, $size: Int!, $ds: [DatasourceSettingsInput!]) {
  meta { dataVersion { year month } }
  disease(efoId: $id) {
    id
    name
    associatedTargets(page: {index: 0, size: $size}, datasources: $ds) {
      count
      datasources { id weight propagate }
      rows {
        score
        target { id approvedSymbol approvedName }
        datatypeScores { id score }
      }
    }
  }
}"""

_DEFAULT_DATASOURCES_QUERY = """
query DefaultWeights($id: String!) {
  disease(efoId: $id) { associatedTargets(page: {index: 0, size: 1}) { datasources { id weight propagate } } }
}"""

_TARGET_DRUGS_QUERY = """
query TargetDrugs($ids: [String!]!) {
  meta { dataVersion { year month } }
  targets(ensemblIds: $ids) {
    id
    approvedSymbol
    drugAndClinicalCandidates {
      rows {
        drug {
          id
          name
          drugType
          maximumClinicalStage
          parentMolecule { id }
          mechanismsOfAction { rows { mechanismOfAction actionType targets { id } } }
        }
      }
    }
  }
}"""

_DRUG_INDICATIONS_QUERY = """
query DrugIndications($ids: [String!]!) {
  drugs(chemblIds: $ids) {
    id
    indications { rows { maxClinicalStage disease { id name } } }
  }
}"""

_DRUG_REG_REPORTS_QUERY = """
query DrugRegulatoryReports($ids: [String!]!) {
  drugs(chemblIds: $ids) {
    id
    indications { rows { clinicalReports { clinicalStage origin year source } } }
  }
}"""

_DRUG_SEARCH_QUERY = """
query FindDrug($q: String!) {
  search(queryString: $q, entityNames: ["drug"], page: {index: 0, size: 1}) { hits { id name } }
}"""

_DRUG_NAMES_QUERY = """
query DrugNames($id: String!) {
  drug(chemblId: $id) { id name synonyms { label } tradeNames { label } }
}"""

_DISEASE_NAMES_QUERY = """
query DiseaseNames($id: String!) {
  disease(efoId: $id) { id name synonyms { relation terms } }
}"""


async def graphql(client: ApiClient, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    payload = await client.post_json(GRAPHQL_URL, {"query": query, "variables": variables})
    if payload.get("errors"):
        messages = "; ".join(e.get("message", str(e)) for e in payload["errors"])
        raise UpstreamError(f"Open Targets GraphQL error: {messages}")
    return payload["data"]


def _data_version(data: dict[str, Any]) -> str | None:
    v = (data.get("meta") or {}).get("dataVersion")
    return f"{v['year']}.{v['month']}" if v else None


async def find_disease(client: ApiClient, name: str, limit: int = 5) -> FindDiseaseResult:
    name = name.strip()
    if not name:
        raise ValueError("Disease name must not be empty.")
    data = await graphql(client, _SEARCH_QUERY, {"q": name, "size": limit})
    hits = [
        DiseaseHit(
            id=h["id"],
            name=h["name"],
            description=h.get("description"),
            source_url=f"{PLATFORM_URL}/disease/{h['id']}",
        )
        for h in data["search"]["hits"]
        if h.get("entity") == "disease"
    ]
    return FindDiseaseResult(query=name, hits=hits)


async def disease_targets(
    client: ApiClient, disease_id: str, limit: int = 20, *, exclude_clinical: bool = False
) -> DiseaseTargetsResult:
    """Top associated targets. exclude_clinical zero-weights the clinical-precedence datasource so
    targets are ranked only on non-drug evidence (used by the recall eval to avoid circularity)."""
    _check_disease_id(disease_id)
    datasources = None
    if exclude_clinical:
        # Passing `datasources` replaces the default weighting entirely, so start from the
        # defaults and only zero out the clinical source.
        defaults = await graphql(client, _DEFAULT_DATASOURCES_QUERY, {"id": disease_id})
        if defaults["disease"] is None:
            raise ValueError(f"Unknown disease ID {disease_id!r}. Use find_disease to look it up.")
        datasources = [
            {"id": d["id"], "weight": d["weight"], "propagate": d["propagate"]}
            for d in defaults["disease"]["associatedTargets"]["datasources"]
            if d["id"] != CLINICAL_DATASOURCE
        ] + [{"id": CLINICAL_DATASOURCE, "weight": 0.0, "propagate": True}]

    data = await graphql(client, _ASSOC_QUERY, {"id": disease_id, "size": limit, "ds": datasources})
    disease = data["disease"]
    if disease is None:
        raise ValueError(f"Unknown disease ID {disease_id!r}. Use find_disease to look it up.")
    assoc = disease["associatedTargets"]
    targets = [
        TargetAssociation(
            target_id=r["target"]["id"],
            symbol=r["target"]["approvedSymbol"],
            name=r["target"]["approvedName"],
            overall_score=round(r["score"], 4),
            datatype_scores={d["id"]: round(d["score"], 4) for d in r["datatypeScores"]},
            source_url=f"{PLATFORM_URL}/evidence/{r['target']['id']}/{disease_id}",
        )
        for r in assoc["rows"]
        if r["score"] > 0
    ]
    return DiseaseTargetsResult(
        disease_id=disease["id"],
        disease_name=disease["name"],
        total_associated_targets=assoc["count"],
        excluded_datasources=[CLINICAL_DATASOURCE] if exclude_clinical else [],
        targets=targets,
        data_version=_data_version(data),
    )


async def approved_drugs_for_targets(
    client: ApiClient,
    target_ids: list[str],
    max_drugs: int = 50,
    *,
    enrich: bool = True,
    today: dt.date | None = None,
) -> ApprovedDrugsResult:
    """Approved drugs acting on the targets. Pass target IDs in priority order (as disease_targets
    returns them): drugs are ordered by their highest-priority target, then by how many targets
    they hit. Salt/hydrate forms are merged into their parent molecule when both are present.

    enrich=False skips approval years, withdrawn flags and indications (one request instead of
    several); used by the recall eval, which only needs the candidate list."""
    today = today or dt.date.today()
    target_ids = list(dict.fromkeys(t.strip() for t in target_ids if t.strip()))
    if not target_ids:
        raise ValueError("Provide at least one Ensembl target ID (e.g. ENSG00000103197).")
    if len(target_ids) > MAX_TARGETS_PER_CALL:
        raise ValueError(f"At most {MAX_TARGETS_PER_CALL} target IDs per call.")
    bad = [t for t in target_ids if not ENSEMBL_RE.match(t)]
    if bad:
        raise ValueError(f"Not Ensembl gene IDs: {bad}. Use the target_id values from disease_targets.")

    data = await graphql(client, _TARGET_DRUGS_QUERY, {"ids": target_ids})
    found = {t["id"]: t for t in data["targets"]}

    # Collect approved drugs, remembering which query targets each one hits.
    drugs: dict[str, dict[str, Any]] = {}
    hits: dict[str, dict[str, str]] = {}
    for tid in target_ids:
        target = found.get(tid)
        if not target:
            continue
        for row in target["drugAndClinicalCandidates"]["rows"]:
            drug = row.get("drug")
            if not drug or drug["maximumClinicalStage"] != "APPROVAL":
                continue
            drugs.setdefault(drug["id"], drug)
            hits.setdefault(drug["id"], {})[tid] = target["approvedSymbol"]

    all_ids = list(drugs)
    parents = {d: drugs[d]["parentMolecule"]["id"] for d in all_ids if drugs[d].get("parentMolecule")}
    # Fold salt/hydrate forms into their parent when the parent is also in the result.
    other_forms: dict[str, list[str]] = {}
    for child, parent in parents.items():
        if parent in drugs and parent != child:
            other_forms.setdefault(parent, []).append(child)
            for tid, sym in hits[child].items():
                hits[parent].setdefault(tid, sym)
    ids = [d for d in all_ids if not (d in parents and parents[d] in drugs and parents[d] != d)]

    order = {t: i for i, t in enumerate(target_ids)}
    ids.sort(key=lambda d: (min(order[t] for t in hits[d]), -len(hits[d]), drugs[d]["name"]))
    total = len(ids)
    ids = ids[:max_drugs]

    forms = {d: [d, *other_forms.get(d, [])] for d in ids}
    family = {d: forms[d] + ([parents[d]] if d in parents and parents[d] != d else []) for d in ids}
    warnings: list[str] = []
    indications: dict[str, list[Indication]] = {}
    molecules: dict[str, dict[str, Any]] = {}
    if enrich:
        indications = await _approved_indications(client, [f for d in ids for f in forms[d]])
        try:
            molecules = await chembl.molecules(client, [m for d in ids for m in family[d]])
        except UpstreamError as exc:
            warnings.append(f"ChEMBL unavailable ({exc}); approval years use the Open Targets fallback.")
    else:
        warnings.append("Not enriched: approval years, withdrawn flags and indications were skipped.")
    years, sources = _approval_years(ids, family, molecules)
    missing = [d for d in ids if years.get(d) is None] if enrich else []
    if missing:
        fallback = await _regulatory_fallback_years(client, missing)
        for d, y in fallback.items():
            years[d] = y
            sources[d] = "Open Targets earliest regulatory approval record (may understate age)"

    result: list[ApprovedDrug] = []
    query_set = set(target_ids)
    for d in ids:
        hits[d] = dict(sorted(hits[d].items(), key=lambda kv: order[kv[0]]))
        merged_indications = {i.disease_id: i for f in forms[d] for i in indications.get(f, [])}
        drug = drugs[d]
        moa_rows = (drug.get("mechanismsOfAction") or {}).get("rows") or []
        mechanisms = [
            Mechanism(
                mechanism_of_action=m["mechanismOfAction"],
                action_type=m.get("actionType"),
                target_ids=[t["id"] for t in m["targets"]],
            )
            for m in moa_rows
        ]
        relevant = [m for m in mechanisms if query_set & set(m.target_ids)]
        year = years.get(d)
        withdrawn = [w for m in family[d] if (w := (molecules.get(m) or {}).get("withdrawn_flag")) is not None]
        result.append(
            ApprovedDrug(
                chembl_id=d,
                name=drug["name"],
                drug_type=drug["drugType"],
                parent_chembl_id=parents.get(d) if parents.get(d) != d else None,
                other_form_chembl_ids=sorted(other_forms.get(d, [])),
                query_target_ids=list(hits[d]),
                query_target_symbols=list(hits[d].values()),
                mechanisms=relevant or mechanisms,
                year_of_first_approval=year,
                approval_year_source=sources.get(d),
                likely_off_patent=None if year is None else (today.year - year) >= OFF_PATENT_YEARS,
                withdrawn_flag=any(withdrawn) if withdrawn else None,
                approved_indications=sorted(merged_indications.values(), key=lambda i: i.disease_name),
                source_url=f"{PLATFORM_URL}/drug/{d}",
            )
        )
    return ApprovedDrugsResult(
        target_ids=target_ids,
        unknown_target_ids=[t for t in target_ids if t not in found],
        total_approved_drugs=total,
        truncated=total > len(result),
        drugs=result,
        warnings=warnings,
        off_patent_heuristic=OFF_PATENT_HEURISTIC.format(years=OFF_PATENT_YEARS, today_year=today.year),
        data_version=_data_version(data),
    )


def _approval_years(
    ids: Iterable[str], family: dict[str, list[str]], molecules: dict[str, dict[str, Any]]
) -> tuple[dict[str, int | None], dict[str, str]]:
    """Earliest ChEMBL first_approval across the drug, its parent and its salt/hydrate forms."""
    years: dict[str, int | None] = {}
    sources: dict[str, str] = {}
    for d in ids:
        dated = [(y, m) for m in family[d] if (y := (molecules.get(m) or {}).get("first_approval"))]
        if not dated:
            years[d] = None
            continue
        year, mol = min(dated)
        years[d] = year
        sources[d] = "ChEMBL first_approval" + ("" if mol == d else f" (related form {mol})")
    return years, sources


async def _approved_indications(client: ApiClient, ids: list[str]) -> dict[str, list[Indication]]:
    out: dict[str, list[Indication]] = {}
    for chunk in _chunks(ids, _CHUNK):
        data = await graphql(client, _DRUG_INDICATIONS_QUERY, {"ids": chunk})
        for drug in data["drugs"]:
            seen: dict[str, Indication] = {}
            for row in drug["indications"]["rows"]:
                dis = row.get("disease")
                if row["maxClinicalStage"] == "APPROVAL" and dis and dis["id"] not in seen:
                    seen[dis["id"]] = Indication(disease_id=dis["id"], disease_name=dis["name"])
            out[drug["id"]] = sorted(seen.values(), key=lambda i: i.disease_name)
    return out


async def _regulatory_fallback_years(client: ApiClient, ids: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for chunk in _chunks(ids, _CHUNK):
        data = await graphql(client, _DRUG_REG_REPORTS_QUERY, {"ids": chunk})
        for drug in data["drugs"]:
            years = [
                r["year"]
                for row in drug["indications"]["rows"]
                for r in row["clinicalReports"]
                if r["clinicalStage"] == "APPROVAL" and r["origin"] == "REGULATORY_AGENCY" and r.get("year")
            ]
            if years:
                out[drug["id"]] = min(years)
    return out


# --- name resolution used by the citation-integrity eval ---------------------------------------

async def drug_names(client: ApiClient, drug: str) -> tuple[str | None, list[str]]:
    """Return (ChEMBL id, match terms) for a drug name or ChEMBL id.

    Only trade names and upper-case synonyms (ChEMBL-curated) are kept: the lower-case synonyms
    come from free-text trial records and include other drugs (e.g. "everolimus" for sirolimus)
    and short ambiguous tokens ("sir", "rapa").
    """
    chembl_id = drug if re.fullmatch(r"CHEMBL\d+", drug.strip(), re.I) else None
    if chembl_id is None:
        data = await graphql(client, _DRUG_SEARCH_QUERY, {"q": drug})
        hits = data["search"]["hits"]
        chembl_id = hits[0]["id"] if hits else None
    terms = {drug.strip()} if not chembl_id or chembl_id != drug.strip() else set()
    if chembl_id:
        d = (await graphql(client, _DRUG_NAMES_QUERY, {"id": chembl_id.upper()}))["drug"]
        if d:
            terms.add(d["name"])
            terms.update(t["label"] for t in d["tradeNames"])
            terms.update(s["label"] for s in d["synonyms"] if s["label"] == s["label"].upper())
    return chembl_id, _clean_terms(terms)


async def disease_names(client: ApiClient, disease_id: str) -> tuple[str, list[str]]:
    """Return (name, match terms): name plus exact, narrow and related synonyms, dropping short
    upper-case abbreviations (e.g. "LAM") that would match unrelated text."""
    d = (await graphql(client, _DISEASE_NAMES_QUERY, {"id": disease_id}))["disease"]
    if d is None:
        raise ValueError(f"Unknown disease ID {disease_id!r}")
    terms = {d["name"]}
    for syn in d["synonyms"] or []:
        if syn["relation"] in {"hasExactSynonym", "hasNarrowSynonym", "hasRelatedSynonym"}:
            terms.update(t for t in syn["terms"] if not (t.isupper() and len(t) <= 6))
    return d["name"], _clean_terms(terms)


def _clean_terms(terms: Iterable[str]) -> list[str]:
    out = set()
    for t in terms:
        t = " ".join(t.split())
        if len(t) >= 4 and len(t) <= 60 and re.search(r"[A-Za-z]{3}", t):
            out.add(t)
    return sorted(out, key=str.lower)


def _check_disease_id(disease_id: str) -> None:
    if not DISEASE_ID_RE.match(disease_id):
        raise ValueError(
            f"{disease_id!r} does not look like an Open Targets disease ID (e.g. MONDO_0011705). "
            "Use find_disease first."
        )


def _chunks(items: list[str], n: int) -> Iterable[list[str]]:
    for i in range(0, len(items), n):
        yield items[i : i + n]
