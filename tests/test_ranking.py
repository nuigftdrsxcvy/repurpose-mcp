from repurpose_mcp.models import ApprovedDrug, ApprovedDrugsResult, DiseaseTargetsResult, TargetAssociation
from repurpose_mcp.ranking import rank_candidates


def _target(tid, sym, score):
    return TargetAssociation(target_id=tid, symbol=sym, name=sym, overall_score=score, datatype_scores={}, source_url="")


def _drug(name, targets):
    return ApprovedDrug(
        chembl_id=f"CHEMBL{len(name)}", name=name, drug_type="Small molecule", query_target_ids=targets,
        query_target_symbols=targets, mechanisms=[], year_of_first_approval=None, likely_off_patent=None,
        approved_indications=[], source_url="",
    )


def test_rank_by_best_target_score_then_breadth_then_name():
    targets = DiseaseTargetsResult(
        disease_id="X_1", disease_name="x", total_associated_targets=3,
        targets=[_target("A", "A", 0.9), _target("B", "B", 0.5), _target("C", "C", 0.5)],
    )
    drugs = ApprovedDrugsResult(
        target_ids=["A", "B", "C"], total_approved_drugs=4, truncated=False, off_patent_heuristic="",
        drugs=[_drug("zeta", ["B"]), _drug("beta", ["B"]), _drug("broad", ["B", "C"]), _drug("top", ["A"])],
    )
    ranked = rank_candidates(targets, drugs)
    assert [r.drug.name for r in ranked] == ["top", "broad", "beta", "zeta"]
    assert ranked[0].rank == 1 and ranked[0].best_target_symbol == "A" and ranked[0].best_target_score == 0.9
