from __future__ import annotations

import pytest

from repurpose_mcp import opentargets
from repurpose_mcp.http import UpstreamError
from tests.conftest import TODAY

LAM = "MONDO_0011705"
FKBP1A = "ENSG00000088832"
MTOR = "ENSG00000198793"


async def test_find_disease(api):
    res = await opentargets.find_disease(api, "lymphangioleiomyomatosis")
    assert res.hits[0].id == LAM
    assert res.hits[0].name == "lymphangioleiomyomatosis"
    assert res.hits[0].source_url.endswith(LAM)


async def test_disease_targets(api):
    res = await opentargets.disease_targets(api, LAM, limit=10)
    assert res.disease_name == "lymphangioleiomyomatosis"
    assert res.total_associated_targets > 100
    assert res.targets[0].symbol == "TSC2"
    assert "genetic_association" in res.targets[0].datatype_scores
    scores = [t.overall_score for t in res.targets]
    assert scores == sorted(scores, reverse=True)
    assert "NOT evidence" in res.note
    fkbp = next(t for t in res.targets if t.symbol == "FKBP1A")
    assert set(fkbp.datatype_scores) == {"clinical"}


async def test_disease_targets_excluding_clinical(api):
    res = await opentargets.disease_targets(api, LAM, limit=10, exclude_clinical=True)
    symbols = [t.symbol for t in res.targets]
    assert symbols[:2] == ["TSC2", "TSC1"]
    # FKBP1A's only evidence is clinical precedence (sirolimus trials), so it drops out
    assert "FKBP1A" not in symbols
    assert res.excluded_datasources == ["clinical_precedence"]


async def test_approved_drugs_for_targets(api):
    res = await opentargets.approved_drugs_for_targets(api, [FKBP1A, MTOR], today=TODAY)
    by_name = {d.name: d for d in res.drugs}
    siro = by_name["SIROLIMUS"]
    assert siro.chembl_id == "CHEMBL413"
    assert siro.year_of_first_approval == 1999
    assert siro.approval_year_source == "ChEMBL first_approval"
    assert siro.likely_off_patent is True
    assert FKBP1A in siro.query_target_ids
    assert any("FKBP1A" in m.mechanism_of_action or FKBP1A in m.target_ids for m in siro.mechanisms)
    assert any(i.disease_id == LAM for i in siro.approved_indications)
    assert "HEURISTIC" in res.off_patent_heuristic

    # everolimus (2009) is under 20 years old at TODAY
    assert by_name["EVEROLIMUS"].likely_off_patent is False
    # FKBP1A was listed first, so its drugs come before MTOR-only drugs
    first_mtor_only = next(i for i, d in enumerate(res.drugs) if d.query_target_ids == [MTOR])
    assert all(FKBP1A in d.query_target_ids for d in res.drugs[:first_mtor_only])
    # salt/hydrate forms are folded into the parent: no duplicate tacrolimus rows
    assert sum("TACROLIMUS" in d.name for d in res.drugs) == 1
    assert res.total_approved_drugs == len(res.drugs) and not res.truncated


async def test_approved_drugs_truncation(api):
    res = await opentargets.approved_drugs_for_targets(api, [FKBP1A], max_drugs=2, today=TODAY)
    assert len(res.drugs) == 2 and res.truncated and res.total_approved_drugs > 2


@pytest.mark.parametrize("bad", [[], ["TSC2"], ["ENSG123"]])
async def test_approved_drugs_rejects_bad_ids(bad):
    with pytest.raises(ValueError):
        await opentargets.approved_drugs_for_targets(None, bad)  # type: ignore[arg-type]


async def test_unknown_disease_id(api):
    with pytest.raises(ValueError, match="Unknown disease"):
        await opentargets.disease_targets(api, "MONDO_9999999")


async def test_malformed_disease_id():
    with pytest.raises(ValueError, match="find_disease"):
        await opentargets.disease_targets(None, "lymphangioleiomyomatosis")  # type: ignore[arg-type]


async def test_drug_names_filters_noisy_synonyms(api):
    chembl_id, terms = await opentargets.drug_names(api, "sirolimus")
    assert chembl_id == "CHEMBL413"
    lowered = {t.lower() for t in terms}
    assert {"sirolimus", "rapamycin", "rapamune"} <= lowered
    assert "everolimus" not in lowered and "sir" not in lowered


async def test_disease_names(api):
    name, terms = await opentargets.disease_names(api, LAM)
    assert name == "lymphangioleiomyomatosis"
    assert "lymphangiomyomatosis" in terms and "LAM" not in terms


def test_graphql_errors_are_raised():
    class Fake:
        async def post_json(self, url, body):
            return {"errors": [{"message": "Field 'knownDrugs' not found"}]}

    import asyncio

    with pytest.raises(UpstreamError, match="knownDrugs"):
        asyncio.run(opentargets.graphql(Fake(), "{}", {}))  # type: ignore[arg-type]
