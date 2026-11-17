"""Citation integrity: check that every PMID / NCT ID cited in a brief exists and that the record
mentions both the drug and the disease it is cited for."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from repurpose_mcp import clinicaltrials, opentargets, pubmed
from repurpose_mcp.http import ApiClient

NCT_RE = re.compile(r"\bNCT\d{8}\b", re.I)
PMID_TAGGED_RE = re.compile(r"PMID\s*:?\s*(\d{1,9})", re.I)
PUBMED_URL_RE = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d{1,9})")
BARE_NUMBER_RE = re.compile(r"(?<![\w.])(\d{6,9})(?![\w.])")
CHEMBL_RE = re.compile(r"\bCHEMBL\d+\b", re.I)


@dataclass
class Citation:
    kind: Literal["PMID", "NCT"]
    id: str
    drug: str | None  # None when cited outside the evidence table
    chembl_id: str | None = None


@dataclass
class CheckResult:
    citation: Citation
    exists: bool
    drug_match: str | None = None  # the term that matched, for auditability
    disease_match: str | None = None
    title: str = ""

    @property
    def passed(self) -> bool:
        if self.citation.drug is None:
            return self.exists and self.disease_match is not None
        return self.exists and self.drug_match is not None and self.disease_match is not None


@dataclass
class TableRow:
    cells: dict[str, str]
    drug: str
    chembl_id: str | None
    citations: list[Citation] = field(default_factory=list)


# --- parsing ------------------------------------------------------------------------------------

def _split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_separator(line: str) -> bool:
    return bool(re.fullmatch(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?", line.strip()))


def _clean_drug(cell: str) -> str:
    cell = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", cell)  # markdown links
    cell = re.sub(r"[*_`]", "", cell)
    cell = CHEMBL_RE.sub("", cell)
    cell = re.sub(r"\(\s*[,;]?\s*\)", "", cell)
    return re.split(r"[(\[/;]|<br", cell)[0].strip(" ,")


def parse_brief(markdown: str) -> tuple[list[TableRow], list[Citation]]:
    """Return (evidence-table rows with their citations, citations found outside the table).

    The evidence table is any markdown table whose header contains a 'Drug' column. PMIDs are
    recognised as 'PMID:123', PubMed URLs, or bare 6-9 digit numbers inside a 'PMID' column."""
    lines = markdown.splitlines()
    rows: list[TableRow] = []
    table_lines: set[int] = set()
    i = 0
    while i < len(lines) - 1:
        if "|" in lines[i] and _is_separator(lines[i + 1]):
            header = [h.lower() for h in _split_row(lines[i])]
            drug_col = next((k for k, h in enumerate(header) if re.sub(r"[^a-z]", "", h) == "drug"), None)
            j = i + 2
            while j < len(lines) and "|" in lines[j] and lines[j].strip():
                j += 1
            if drug_col is not None:
                table_lines.update(range(i, j))
                for line in lines[i + 2 : j]:
                    cells = _split_row(line)
                    cells += [""] * (len(header) - len(cells))
                    named = dict(zip(header, cells))
                    drug_cell = cells[drug_col]
                    chembl = CHEMBL_RE.search(drug_cell)
                    row = TableRow(
                        cells=named,
                        drug=_clean_drug(drug_cell),
                        chembl_id=chembl.group(0).upper() if chembl else None,
                    )
                    for h, cell in named.items():
                        for kind, ident in _ids_in(cell, pmid_column="pmid" in h):
                            row.citations.append(Citation(kind, ident, row.drug, row.chembl_id))
                    row.citations = _dedupe(row.citations)
                    rows.append(row)
            i = j
        else:
            i += 1

    outside = [
        Citation(kind, ident, None)
        for n, line in enumerate(lines)
        if n not in table_lines
        for kind, ident in _ids_in(line, pmid_column=False)
    ]
    in_table = {(c.kind, c.id) for r in rows for c in r.citations}
    outside = [c for c in _dedupe(outside) if (c.kind, c.id) not in in_table]
    return rows, outside


def _ids_in(text: str, *, pmid_column: bool) -> list[tuple[Literal["PMID", "NCT"], str]]:
    found: list[tuple[Literal["PMID", "NCT"], str]] = [("NCT", m.upper()) for m in NCT_RE.findall(text)]
    pmids = PMID_TAGGED_RE.findall(text) + PUBMED_URL_RE.findall(text)
    if pmid_column:
        pmids += BARE_NUMBER_RE.findall(NCT_RE.sub("", text))
    found += [("PMID", p.lstrip("0")) for p in pmids]
    return found


def _dedupe(cites: list[Citation]) -> list[Citation]:
    seen: set[tuple[str, str, str | None]] = set()
    out = []
    for c in cites:
        key = (c.kind, c.id, c.drug)
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


# --- matching -----------------------------------------------------------------------------------

def normalise(text: str) -> str:
    return " " + " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split()) + " "


def find_term(terms: list[str], text: str) -> str | None:
    """First term occurring in text as whole words (case/punctuation-insensitive)."""
    norm = normalise(text)
    for t in sorted(terms, key=len, reverse=True):
        nt = normalise(t)
        if nt.strip() and nt in norm:
            return t
    return None


# --- fetching -----------------------------------------------------------------------------------

def study_text(study: dict[str, Any]) -> tuple[str, str]:
    """(title, searchable text) from a ClinicalTrials.gov v2 study record."""
    p = study.get("protocolSection", {})
    ident = p.get("identificationModule", {})
    conds = p.get("conditionsModule", {})
    arms = p.get("armsInterventionsModule", {})
    desc = p.get("descriptionModule", {})
    derived = study.get("derivedSection", {})
    parts = [ident.get("briefTitle", ""), ident.get("officialTitle", ""), desc.get("briefSummary", "")]
    parts += conds.get("conditions", []) + conds.get("keywords", [])
    for iv in arms.get("interventions", []):
        parts += [iv.get("name", "")] + iv.get("otherNames", [])
    for mod in ("conditionBrowseModule", "interventionBrowseModule"):
        parts += [m.get("term", "") for m in derived.get(mod, {}).get("meshes", [])]
    return ident.get("briefTitle", ""), "\n".join(parts)


async def check_citations(
    client: ApiClient, citations: list[Citation], disease_terms: list[str]
) -> list[CheckResult]:
    pmids = [c.id for c in citations if c.kind == "PMID"]
    records = await pubmed.fetch_records(client, pmids) if pmids else {}
    studies: dict[str, tuple[str, str] | None] = {}
    for nct in sorted({c.id for c in citations if c.kind == "NCT"}):
        study = await clinicaltrials.get_study(client, nct)
        studies[nct] = study_text(study) if study else None

    drug_terms: dict[tuple[str | None, str | None], list[str]] = {}
    results = []
    for c in citations:
        if c.kind == "PMID":
            rec = records.get(c.id)
            title, text = (rec["title"], rec["text"]) if rec else ("", "")
            exists = rec is not None
        else:
            st = studies.get(c.id)
            title, text = st if st else ("", "")
            exists = st is not None
        res = CheckResult(citation=c, exists=exists, title=title)
        if exists:
            res.disease_match = find_term(disease_terms, text)
            if c.drug is not None:
                key = (c.drug, c.chembl_id)
                if key not in drug_terms:
                    _, terms = await opentargets.drug_names(client, c.chembl_id or c.drug)
                    drug_terms[key] = sorted({*terms, c.drug})
                res.drug_match = find_term(drug_terms[key], text)
        results.append(res)
    return results
