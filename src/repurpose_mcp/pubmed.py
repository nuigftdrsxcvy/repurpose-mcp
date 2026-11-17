"""NCBI E-utilities (PubMed). Reads NCBI_API_KEY (and optionally NCBI_EMAIL) from the environment."""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from typing import Any

from repurpose_mcp.http import NCBI_INTERVAL_WITH_KEY, ApiClient
from repurpose_mcp.models import Article, LiteratureResult

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
NCBI_HOST = "eutils.ncbi.nlm.nih.gov"
PUBMED_URL = "https://pubmed.ncbi.nlm.nih.gov"


def _common_params(client: ApiClient) -> dict[str, str]:
    params = {"tool": "repurpose-mcp"}
    if email := os.environ.get("NCBI_EMAIL"):
        params["email"] = email
    if key := os.environ.get("NCBI_API_KEY"):
        params["api_key"] = key
        client.set_host_interval(NCBI_HOST, NCBI_INTERVAL_WITH_KEY)
    return params


def build_query(drug: str, disease: str) -> str:
    # Parenthesised plain terms let PubMed's automatic term mapping add MeSH and synonyms.
    clean = lambda s: re.sub(r'["()\[\]]', " ", s).strip()  # noqa: E731
    return f"({clean(drug)}) AND ({clean(disease)})"


async def literature(client: ApiClient, drug: str, disease: str, max_results: int = 10) -> LiteratureResult:
    drug, disease = drug.strip(), disease.strip()
    if not drug or not disease:
        raise ValueError("Both drug and disease are required.")
    common = _common_params(client)
    term = build_query(drug, disease)
    search = await client.get_json(
        f"{EUTILS}/esearch.fcgi",
        {**common, "db": "pubmed", "term": term, "retmax": max_results, "retmode": "json", "sort": "relevance"},
    )
    res = search.get("esearchresult", {})
    if "ERROR" in res:
        raise ValueError(f"PubMed rejected the query: {res['ERROR']}")
    pmids: list[str] = res.get("idlist", [])
    articles: list[Article] = []
    if pmids:
        summary = await client.get_json(
            f"{EUTILS}/esummary.fcgi", {**common, "db": "pubmed", "id": ",".join(pmids), "retmode": "json"}
        )
        records = summary.get("result", {})
        for pmid in pmids:  # keep relevance order
            rec = records.get(pmid)
            if rec and "error" not in rec:
                articles.append(
                    Article(
                        pmid=pmid,
                        title=rec.get("title", "").strip(),
                        year=_year(rec.get("sortpubdate") or rec.get("pubdate", "")),
                        journal=rec.get("source"),
                        url=f"{PUBMED_URL}/{pmid}/",
                    )
                )
    return LiteratureResult(
        drug=drug,
        disease=disease,
        query=term,
        query_translation=res.get("querytranslation"),
        total_count=int(res.get("count", 0)),
        articles=articles,
    )


async def fetch_records(client: ApiClient, pmids: list[str]) -> dict[str, dict[str, Any]]:
    """PMID -> {"title", "text"} where text includes title, abstract, MeSH, chemicals and keywords.
    PMIDs that do not exist are absent from the result."""
    out: dict[str, dict[str, Any]] = {}
    common = _common_params(client)
    ids = sorted(set(pmids))
    for i in range(0, len(ids), 200):
        xml = await client.get_text(
            f"{EUTILS}/efetch.fcgi", {**common, "db": "pubmed", "id": ",".join(ids[i : i + 200]), "retmode": "xml"}
        )
        root = ET.fromstring(xml)
        for art in root.iter("PubmedArticle"):
            pmid = art.findtext("MedlineCitation/PMID")
            if not pmid:
                continue
            title_el = art.find("MedlineCitation/Article/ArticleTitle")
            title = "".join(title_el.itertext()) if title_el is not None else ""
            parts = [title]
            parts += ["".join(a.itertext()) for a in art.iter("AbstractText")]
            parts += [m.text or "" for m in art.iter("DescriptorName")]
            parts += [c.text or "" for c in art.iter("NameOfSubstance")]
            parts += [k.text or "" for k in art.iter("Keyword")]
            out[pmid] = {"title": title, "text": "\n".join(parts)}
    return out


def _year(date: str) -> int | None:
    m = re.match(r"(\d{4})", date)
    return int(m.group(1)) if m else None
