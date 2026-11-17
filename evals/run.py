"""Evaluation harness for repurpose-mcp. Writes evals/results.md.

a) Citation integrity: for each generated brief, check that every PMID and NCT ID exists and that
   the record mentions both the drug (its row in the evidence table) and the disease.
b) Recall: for known repurposing cases (CSV), check whether the expected drug appears in the top N
   candidates produced by the tool pipeline (find_disease -> disease_targets ->
   approved_drugs_for_targets -> rank by best target association score). Run twice: with default
   Open Targets scoring, and with the clinical-precedence datasource zero-weighted, because default
   scores already include the trials/approvals that make a case "known" (circular).

Usage:
    uv run python evals/run.py                         # all briefs in evals/briefs/, cases CSV
    uv run python evals/run.py --brief my_brief.md --disease-id MONDO_0011705
    uv run python evals/run.py --skip-integrity --cases evals/known_cases.csv --top-n 10
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from repurpose_mcp import citations, opentargets
from repurpose_mcp.http import ApiClient
from repurpose_mcp.ranking import RankedCandidate, rank_candidates

HERE = Path(__file__).parent
DISEASE_ID_RE = re.compile(r"\b(?:MONDO|EFO|Orphanet|HP|DOID|OTAR)_\d+\b")


# --- (a) citation integrity --------------------------------------------------------------------

@dataclass
class BriefReport:
    path: Path
    disease_id: str
    disease_name: str
    disease_terms: list[str]
    table_results: list[citations.CheckResult]
    outside_results: list[citations.CheckResult]
    n_rows: int


async def check_brief(client: ApiClient, path: Path, disease_id: str | None) -> BriefReport:
    text = path.read_text(encoding="utf-8")
    if disease_id is None:
        m = DISEASE_ID_RE.search(text)
        if not m:
            raise SystemExit(f"{path}: no disease ID found in the brief; pass --disease-id")
        disease_id = m.group(0)
    name, terms = await opentargets.disease_names(client, disease_id)
    rows, outside = citations.parse_brief(text)
    table_cites = [c for r in rows for c in r.citations]
    table_results = await citations.check_citations(client, table_cites, terms)
    outside_results = await citations.check_citations(client, outside, terms)
    return BriefReport(path, disease_id, name, terms, table_results, outside_results, len(rows))


def _pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "n/a (0 citations)"


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(HERE.parent).as_posix()
    except ValueError:
        return path.as_posix()


def _md(text: str | None) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


def integrity_section(reports: list[BriefReport]) -> list[str]:
    out = ["## (a) Citation integrity", ""]
    out.append(
        "A citation **passes** when the record exists and its text (PubMed: title, abstract, MeSH, "
        "substances, keywords; ClinicalTrials.gov: titles, summary, conditions, interventions, "
        "MeSH) mentions both the drug of its table row and the disease. Drug terms: name, trade "
        "names and curated ChEMBL synonyms. Disease terms: Open Targets name plus exact, narrow "
        "and related synonyms (short abbreviations excluded). Citations outside the evidence table "
        "are checked for existence and disease mention only."
    )
    out.append("")
    if not reports:
        out += ["_No briefs found. Put generated briefs in `evals/briefs/` or pass `--brief`._", ""]
        return out
    all_results = [r for rep in reports for r in rep.table_results + rep.outside_results]
    out.append(f"**Overall pass rate: {_pct(sum(r.passed for r in all_results), len(all_results))}**")
    out.append("")
    out.append("| Brief | Disease | Table rows | PMIDs pass | NCTs pass | Outside-table pass | Not found | Drug not mentioned | Disease not mentioned |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for rep in reports:
        tr = rep.table_results
        pm = [r for r in tr if r.citation.kind == "PMID"]
        nc = [r for r in tr if r.citation.kind == "NCT"]
        everything = tr + rep.outside_results
        out.append(
            f"| `{rep.path.name}` | {rep.disease_name} ({rep.disease_id}) | {rep.n_rows} "
            f"| {_pct(sum(r.passed for r in pm), len(pm))} | {_pct(sum(r.passed for r in nc), len(nc))} "
            f"| {_pct(sum(r.passed for r in rep.outside_results), len(rep.outside_results))} "
            f"| {sum(not r.exists for r in everything)} "
            f"| {sum(r.exists and r.citation.drug is not None and not r.drug_match for r in everything)} "
            f"| {sum(r.exists and not r.disease_match for r in everything)} |"
        )
    out.append("")
    for rep in reports:
        out.append(f"### `{rep.path.name}`: every citation")
        out.append("")
        out.append("| Result | ID | Cited for drug | Exists | Drug term matched | Disease term matched | Record title |")
        out.append("|---|---|---|---|---|---|---|")
        for r in rep.table_results + rep.outside_results:
            c = r.citation
            out.append(
                f"| {'PASS' if r.passed else '**FAIL**'} | {c.id if c.kind == 'NCT' else 'PMID:' + c.id} "
                f"| {_md(c.drug) if c.drug is not None else '_(outside table)_'} | {'yes' if r.exists else '**no**'} "
                f"| {_md(r.drug_match) if c.drug is not None else 'n/a'} | {_md(r.disease_match)} "
                f"| {_md(r.title)[:120]} |"
            )
        out.append("")
    return out


# --- (b) recall ---------------------------------------------------------------------------------

@dataclass
class Case:
    disease: str
    expected_drug: str
    disease_id: str | None
    expected_chembl_id: str | None
    notes: str


@dataclass
class CaseResult:
    case: Case
    disease_id: str
    disease_name: str
    n_candidates: dict[str, int]
    rank: dict[str, int | None]
    matched: dict[str, RankedCandidate | None]
    error: str | None = None


MODES = {"default": False, "no_clinical": True}


def load_cases(path: Path) -> list[Case]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = {"disease", "expected_drug"} - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"{path}: missing required column(s) {sorted(missing)}")
        return [
            Case(
                disease=row["disease"].strip(),
                expected_drug=row["expected_drug"].strip(),
                disease_id=(row.get("disease_id") or "").strip() or None,
                expected_chembl_id=(row.get("expected_chembl_id") or "").strip().upper() or None,
                notes=(row.get("notes") or "").strip(),
            )
            for row in reader
            if (row.get("disease") or "").strip() and not row["disease"].lstrip().startswith("#")
        ]


def matches(case: Case, cand: RankedCandidate) -> bool:
    d = cand.drug
    if case.expected_chembl_id:
        return case.expected_chembl_id in {d.chembl_id, d.parent_chembl_id, *d.other_form_chembl_ids}
    want = citations.normalise(case.expected_drug)
    have = citations.normalise(d.name)
    return have == want or have.startswith(want)  # e.g. "TACROLIMUS ANHYDROUS" for "tacrolimus"


async def run_case(client: ApiClient, case: Case, n_targets: int) -> CaseResult:
    disease_id, disease_name = case.disease_id, case.disease
    if disease_id is None:
        found = await opentargets.find_disease(client, case.disease, limit=1)
        if not found.hits:
            return CaseResult(case, "", "", {}, {}, {}, error="disease not found")
        disease_id, disease_name = found.hits[0].id, found.hits[0].name
    res = CaseResult(case, disease_id, disease_name, {}, {}, {})
    for mode, exclude in MODES.items():
        targets = await opentargets.disease_targets(client, disease_id, n_targets, exclude_clinical=exclude)
        res.disease_name = targets.disease_name
        if not targets.targets:
            res.n_candidates[mode], res.rank[mode], res.matched[mode] = 0, None, None
            continue
        drugs = await opentargets.approved_drugs_for_targets(
            client, [t.target_id for t in targets.targets], max_drugs=1000, enrich=False
        )
        ranked = rank_candidates(targets, drugs)
        hit = next((c for c in ranked if matches(case, c)), None)
        res.n_candidates[mode] = len(ranked)
        res.rank[mode] = hit.rank if hit else None
        res.matched[mode] = hit
    return res


def recall_section(results: list[CaseResult], cases_path: Path, top_n: int, n_targets: int, example: bool) -> list[str]:
    out = ["## (b) Recall on known repurposing cases", ""]
    if example:
        out += [
            "> **These are the bundled EXAMPLE cases (`known_cases.example.csv`), not a verified "
            "set.** Create `evals/known_cases.csv` with your verified cases and re-run.",
            "",
        ]
    out.append(
        f"Cases: `{_rel(cases_path)}`. Pipeline: top {n_targets} Open Targets targets -> all approved "
        f"drugs on them -> ranked by the best association score among each drug's targets. "
        f"A case is a hit if the expected drug is in the top {top_n}."
    )
    out.append("")
    out.append(
        "- **default**: standard Open Targets association scores. These include the "
        "`clinical_precedence` datasource (drugs trialled or approved for the disease), so a known "
        "repurposing success can rank its own target highly. Treat it as an upper bound.\n"
        "- **no_clinical**: the same with `clinical_precedence` zero-weighted, so only genetic, "
        "literature, pathway, animal-model etc. evidence ranks targets. This is closer to the real "
        "prospective use case."
    )
    out.append("")
    ok = [r for r in results if not r.error]
    for mode in MODES:
        hits = sum(1 for r in ok if r.rank.get(mode) is not None and r.rank[mode] <= top_n)
        anywhere = sum(1 for r in ok if r.rank.get(mode) is not None)
        out.append(
            f"- **Recall@{top_n} ({mode}): {_pct(hits, len(ok))}**; "
            f"found anywhere in candidate list: {_pct(anywhere, len(ok))}"
        )
    out.append("")
    out.append(
        f"| Disease (as given) | Resolved to | Expected drug | Rank (default) | Rank (no_clinical) "
        f"| Hit@{top_n} default / no_clinical | Via target | Candidates (default / no_clinical) | Notes |"
    )
    out.append("|---|---|---|---|---|---|---|---|---|")
    for r in results:
        if r.error:
            out.append(f"| {_md(r.case.disease)} | **{r.error}** | {_md(r.case.expected_drug)} | | | | | | {_md(r.case.notes)} |")
            continue
        rk = {m: r.rank.get(m) for m in MODES}
        hit = " / ".join("yes" if rk[m] is not None and rk[m] <= top_n else "no" for m in MODES)
        via = next((f"{c.best_target_symbol} ({c.best_target_score:.2f})" for c in [r.matched.get("default")] if c), "-")
        drug = r.case.expected_drug + (f" ({r.case.expected_chembl_id})" if r.case.expected_chembl_id else "")
        out.append(
            f"| {_md(r.case.disease)} | {_md(r.disease_name)} ({r.disease_id}) | {_md(drug)} "
            f"| {rk['default'] or 'not found'} | {rk['no_clinical'] or 'not found'} | {hit} | {via} "
            f"| {r.n_candidates.get('default', 0)} / {r.n_candidates.get('no_clinical', 0)} | {_md(r.case.notes)} |"
        )
    out.append("")
    out.append(
        "Check the **Resolved to** column: cases without a `disease_id` use the top `find_disease` "
        "hit, which may not be the disease you meant."
    )
    out.append("")
    return out


# --- main ---------------------------------------------------------------------------------------

async def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--brief", action="append", type=Path, help="brief markdown file (repeatable); default evals/briefs/*.md")
    ap.add_argument("--disease-id", help="disease ID for --brief (default: first disease ID found in the brief)")
    ap.add_argument("--cases", type=Path, help="CSV of known cases (default evals/known_cases.csv, else the example)")
    ap.add_argument("--top-n", type=int, default=10)
    ap.add_argument("--targets", type=int, default=20, help="targets per disease (matches the brief prompt)")
    ap.add_argument("--out", type=Path, default=HERE / "results.md")
    ap.add_argument("--skip-integrity", action="store_true")
    ap.add_argument("--skip-recall", action="store_true")
    args = ap.parse_args(argv)

    lines = [
        "# repurpose-mcp evaluation results",
        "",
        f"Run: {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} · command: `python evals/run.py {' '.join(argv if argv is not None else sys.argv[1:])}`".rstrip(),
        "",
    ]
    async with ApiClient() as client:
        meta = await opentargets.graphql(client, "{ meta { apiVersion { x y z } dataVersion { year month } } }", {})
        av, dv = meta["meta"]["apiVersion"], meta["meta"]["dataVersion"]
        lines += [f"Open Targets API {av['x']}.{av['y']}.{av['z']}, data release {dv['year']}.{dv['month']}.", ""]

        if not args.skip_integrity:
            briefs = args.brief or sorted((HERE / "briefs").glob("*.md"))
            reports = []
            for path in briefs:
                print(f"[integrity] {path}", file=sys.stderr)
                reports.append(await check_brief(client, path, args.disease_id))
            lines += integrity_section(reports)

        if not args.skip_recall:
            cases_path = args.cases or HERE / "known_cases.csv"
            example = False
            if args.cases is None and not cases_path.exists():
                cases_path, example = HERE / "known_cases.example.csv", True
            cases = load_cases(cases_path)
            results = []
            for case in cases:
                print(f"[recall] {case.disease} / {case.expected_drug}", file=sys.stderr)
                try:
                    results.append(await run_case(client, case, args.targets))
                except Exception as exc:  # report and keep going
                    results.append(CaseResult(case, "", "", {}, {}, {}, error=f"error: {exc}"))
            lines += recall_section(results, cases_path, args.top_n, args.targets, example)

    args.out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
