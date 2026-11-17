from __future__ import annotations

from repurpose_mcp.citations import Citation, check_citations, find_term, parse_brief

BRIEF = """\
# Brief: lymphangioleiomyomatosis (MONDO_0011705)

See also PMID: 34461049 for a review.

| Drug | Target | Mechanism | Approval year | Off-patent heuristic | Trials | PMIDs | Evidence strength | Gaps |
|---|---|---|---|---|---|---|---|---|
| **SIROLIMUS** (CHEMBL413) | FKBP1A | FKBP12 inhibitor | 1999 | likely (heuristic) | NCT00414648 (Ph3) | PMID:21410393, 99999999 | Strong | long-term |
| [Doxycycline](https://x) | MMP2 | MMP inhibitor | 1967 | likely (heuristic) | none found | https://pubmed.ncbi.nlm.nih.gov/21410393/ | Weak | n/a |
"""


def test_parse_brief():
    rows, outside = parse_brief(BRIEF)
    assert [r.drug for r in rows] == ["SIROLIMUS", "Doxycycline"]
    assert rows[0].chembl_id == "CHEMBL413"
    assert {(c.kind, c.id) for c in rows[0].citations} == {
        ("NCT", "NCT00414648"),
        ("PMID", "21410393"),
        ("PMID", "99999999"),
    }
    assert [(c.kind, c.id) for c in rows[1].citations] == [("PMID", "21410393")]
    assert [(c.kind, c.id, c.drug) for c in outside] == [("PMID", "34461049", None)]


def test_bare_numbers_only_count_in_pmid_column():
    rows, _ = parse_brief(
        "| Drug | Approval year | Trials | PMIDs |\n|---|---|---|---|\n| X | 1999 | n=123456 | 7654321 |\n"
    )
    assert [c.id for c in rows[0].citations] == ["7654321"]


def test_find_term_whole_words():
    assert find_term(["sirolimus"], "Sirolimus-eluting stent") == "sirolimus"
    assert find_term(["LAM"], "Lamivudine") is None
    assert find_term(["tuberous sclerosis"], "TUBEROUS  SCLEROSIS complex") == "tuberous sclerosis"


async def test_check_citations(api):
    disease_terms = ["lymphangioleiomyomatosis", "lymphangiomyomatosis"]
    cites = [
        Citation("PMID", "21410393", "SIROLIMUS", "CHEMBL413"),  # MILES trial paper: pass
        Citation("PMID", "99999999999", "SIROLIMUS", "CHEMBL413"),  # does not exist
        Citation("PMID", "21410393", "Doxycycline"),  # real paper, wrong drug
        Citation("NCT", "NCT00414648", "SIROLIMUS", "CHEMBL413"),  # pass
        Citation("NCT", "NCT09999999", "SIROLIMUS", "CHEMBL413"),  # does not exist
        # ClinicalTrials.gov's synonym expansion returns this sirolimus trial for "temsirolimus":
        # the checker must not accept it as temsirolimus evidence.
        Citation("NCT", "NCT00414648", "TEMSIROLIMUS", "CHEMBL1201182"),
    ]
    results = await check_citations(api, cites, disease_terms)
    outcome = [(r.citation.id, r.exists, r.passed) for r in results]
    assert outcome == [
        ("21410393", True, True),
        ("99999999999", False, False),
        ("21410393", True, False),
        ("NCT00414648", True, True),
        ("NCT09999999", False, False),
        ("NCT00414648", True, False),
    ]
    assert results[2].disease_match and results[2].drug_match is None
