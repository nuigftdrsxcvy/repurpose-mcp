# repurpose-mcp

An MCP server that helps rare disease clinicians and trial teams find **approved drugs, probably
off-patent, with a plausible mechanism for a disease**. Every claim it makes is traceable to a
public record: an Open Targets or ChEMBL ID, a ClinicalTrials.gov NCT number, or a PubMed PMID.

It is a **hypothesis-generation tool for research teams**, not a source of clinical advice.

## Key finding

The pipeline mostly **re-finds** repurposing that has already been trialled. It almost never
**predicts** it.

| Recall@10 on 7 known repurposing cases | Result |
|---|---|
| Standard Open Targets association scores | 4/7 |
| With prior clinical evidence (`clinical_precedence`) removed | 0/7 |

Standard scores include each drug's own trials for the disease, so the first number is partly
circular. The second is closer to real prospective use, and it drops to zero.

The main reason is mechanistic. The tool only finds drugs that act **directly** on a
disease-linked gene. Classic repurposing often works **downstream**. In LAM the disease gene is
*TSC2*, but sirolimus acts on mTOR (via FKBP1A), a different protein further along the same
pathway. Closing that gap, for example with one-hop pathway expansion, is the next step.

Cases are in [`evals/known_cases.csv`](evals/known_cases.csv), each checked against a primary
source (trial registration, publication or regulatory approval). They cover five approved
repurposings, one positive trial and one negative trial. Full results:
[`evals/results.md`](evals/results.md).

## What it does

Ask Claude (Desktop or Code) for a repurposing brief on a disease. Claude then uses five tools that
query public databases live:

| Step | Tool | Source | What you get |
|---|---|---|---|
| 1 | `find_disease` | Open Targets Platform | Disease ID (MONDO/EFO/Orphanet) and name, with alternatives |
| 2 | `disease_targets` | Open Targets Platform | Genes/proteins most associated with the disease, with an overall score and a score per evidence type (genetics, somatic mutations, literature, animal models, prior clinical use…) |
| 3 | `approved_drugs_for_targets` | Open Targets + ChEMBL | Approved drugs acting on those targets: ChEMBL ID, mechanism of action, first approval year, approved indications, withdrawn flag, and a `likely_off_patent` **heuristic** |
| 4 | `existing_trials` | ClinicalTrials.gov API v2 | Trials of the drug in the disease: NCT ID, title, phase, status, enrolment |
| 5 | `literature` | PubMed (NCBI E-utilities) | Articles mentioning both drug and disease: PMID, title, year, journal |

The `repurposing_brief` prompt chains these together and asks Claude to produce one evidence table:

| Drug | Target | Mechanism | Approval year | Off-patent heuristic | Trials | PMIDs | Evidence strength | Gaps |
|---|---|---|---|---|---|---|---|---|

The prompt forbids uncited claims ("no claim without an ID") and invented identifiers. It also
requires a grade for evidence strength (Strong / Moderate / Weak / Mechanistic only) based only on
the records retrieved, and a stated reason for any downgrade.

## Example output

Excerpt from a brief for lymphangioleiomyomatosis (LAM), produced 2026-11-17 with Open Targets data
release 26.09 (full brief: [`evals/briefs/lymphangioleiomyomatosis.md`](evals/briefs/lymphangioleiomyomatosis.md)):

> **Disease:** lymphangioleiomyomatosis (MONDO_0011705) · Open Targets data 26.09
>
> | Drug | Target | Mechanism | Approval year | Off-patent heuristic | Trials | PMIDs | Evidence strength | Gaps |
> |---|---|---|---|---|---|---|---|---|
> | NINTEDANIB (CHEMBL502835) | PDGFRB (ENSG00000113721, 0.10); FGFR4, FLT4, FGFR2 | PDGFR / VEGFR / FGFR inhibitor | 2014 (ChEMBL) | unlikely (heuristic) | NCT03062943 (Ph2, completed, n=30) | PMID:39489895 | Moderate | Downgraded from Strong: single-arm, open-label. No randomised comparison with sirolimus. |
> | CELECOXIB (CHEMBL118) | PTGS2 (ENSG00000073756, 0.09) | Cyclooxygenase-2 inhibitor | 1998 (ChEMBL) | likely (heuristic) | NCT02484664 (Ph2, completed, n=12) | PMID:32060062 | Weak | 12-participant pilot; the publication reports a phase I trial. Weak target association. |
> | IMATINIB (CHEMBL941) | PDGFRB (0.10); ABL1 (0.09) | ABL / PDGFR-beta inhibitor | 2001 (ChEMBL) | likely (heuristic) | NCT03131999 (Ph1/2, completed, n=18); NCT06889168 (Ph1, recruiting) | none found | Weak | Pilot with n<20; no published LAM results retrieved. |
>
> **Already approved for this disease:** SIROLIMUS (CHEMBL413). NCT00414648 (Ph3, n=89); PMID:31429781.

## Limitations: read before using results

- **Not clinical advice.** Output is a starting point for expert review, ethics and regulatory
  processes, not a treatment recommendation.
- **`likely_off_patent` is a heuristic.** It is true when the first approval year is at least
  20 years ago. It does not search patents. Formulation, method-of-use, paediatric and orphan
  exclusivities can outlast the compound patent. Old biologics may have no biosimilar. Generic
  availability differs by country. Verify in the
  [FDA Orange Book](https://www.accessdata.fda.gov/scripts/cder/ob/) (small molecules),
  [Purple Book](https://purplebooksearch.fda.gov/) (biologics), or your national equivalent.
- **Approval year source.** First approval year comes from ChEMBL `first_approval` (largely US
  FDA). When ChEMBL has no year, it falls back to the earliest regulatory approval in Open Targets
  (often EMA), which can understate a drug's age. The `approval_year_source` field says which was
  used.
- **Association scores are not efficacy evidence.** An Open Targets score (0–1) summarises how much
  evidence links a gene to a disease. It says nothing about whether a drug acting on that gene
  helps patients. The "clinical" evidence type means drugs have already been trialled, so targets
  of already-tested drugs score higher.
- **Direct targets only.** Drugs are found only if they act directly on an associated target. Drugs
  that act downstream of a disease gene are missed unless that target is itself associated. For
  example, sirolimus acts downstream of TSC2 loss in LAM. The recall eval shows how large this blind
  spot is (see below).
- **Searches are imperfect.** ClinicalTrials.gov and PubMed expand synonyms, so results can include
  irrelevant records. For example, a "temsirolimus" trial search returns sirolimus trials. They can
  also miss relevant ones (non-English, unindexed, conference abstracts, unregistered trials). Read
  the titles.
- **Mechanism annotations are coarse.** For example, tacrolimus and sirolimus share the ChEMBL
  "FKBP1A inhibitor" annotation but act on different downstream pathways.
- **Data freshness.** Results reflect the live databases on the day you run them. Open Targets
  releases quarterly.

## Install

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) and an internet
connection. Then download or clone this folder, for example to `C:\tools\repurpose_mcp` or
`~/tools/repurpose_mcp`, and run `uv sync` inside it once.

An **NCBI API key** is optional but recommended: it raises PubMed's rate limit from 3 to 10 requests
per second. You can get one free from your NCBI account settings. Set it as `NCBI_API_KEY`.

### Claude Desktop

Open *Settings → Developer → Edit Config* and add the server to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "repurpose-mcp": {
      "command": "uv",
      "args": ["run", "--directory", "/ABSOLUTE/PATH/TO/repurpose_mcp", "python", "-m", "repurpose_mcp"],
      "env": { "NCBI_API_KEY": "optional-your-key" }
    }
  }
}
```

On Windows use a path like `"C:\\tools\\repurpose_mcp"`. If Claude Desktop cannot find `uv`, put
the full path to the `uv` executable in `command` (`where uv` on Windows, `which uv` on macOS).
Restart Claude Desktop. To run the brief, click **+** → *repurpose-mcp* → **repurposing_brief**,
enter the disease, and send.

### Claude Code

```bash
claude mcp add repurpose-mcp -e NCBI_API_KEY=your-key -- uv run --directory /ABSOLUTE/PATH/TO/repurpose_mcp python -m repurpose_mcp
```

Then type `/mcp__repurpose-mcp__repurposing_brief "Erdheim-Chester disease"`, or just ask, for
example "find approved drugs that might be repurposed for Castleman disease, with sources".

> The configs use `python -m repurpose_mcp` rather than the `repurpose-mcp` console script.
> Windows Smart App Control can block the unsigned launcher `.exe` that uv generates.

## Evaluations

`uv run python evals/run.py` writes [`evals/results.md`](evals/results.md). It has two parts:

**(a) Citation integrity.** For each brief in `evals/briefs/`, every PMID and NCT ID is fetched
and checked. A citation passes if the record exists and mentions both the drug of its table row
(name, trade names or curated synonyms) and the disease (name or synonyms). To check your own
brief, save Claude's output as a `.md` file in that folder, or run with `--brief file.md`. Passing
means the record is real and on topic; it does not mean the record supports the claim made.

**(b) Recall on known repurposing cases.** For each case in `evals/known_cases.csv`, the eval
checks whether the expected drug is in the top N candidates (default 10). Candidates are ranked by
their best target association score. CSV columns:

```csv
disease,expected_drug,disease_id,expected_chembl_id,notes
lymphangioleiomyomatosis,sirolimus,MONDO_0011705,CHEMBL413,approved for LAM 2015
```

Only `disease` and `expected_drug` are required. Give `disease_id` to avoid mis-resolving the
disease name, and `expected_chembl_id` for exact drug matching. Until you add your verified file,
the eval uses `evals/known_cases.example.csv` (unverified examples) and says so in the results.

Recall runs twice. **default** uses standard Open Targets scores, which include the known
repurposing's own trials, so the test is partly circular. **no_clinical** zero-weights that
clinical evidence, which is closer to finding something new. On the example cases (2026-11-17),
recall@10 was 4/7 by default and **0/7 with clinical evidence removed**. In practice, the tool
re-surfaces repurposing that is already in the clinical record much more reliably than it predicts
new repurposing, mainly because of the direct-target limitation above.

## Development

```bash
uv sync
uv run pytest                          # offline: replays recorded API responses (tests/cassettes)
REPURPOSE_RECORD=1 uv run pytest       # re-record against the live APIs
```

Engineering notes:
- Requests use httpx with timeouts and up to four attempts, with exponential backoff and
  `Retry-After` support, on 429/5xx and network errors.
- Rate limiting is per host: Open Targets and ChEMBL 5/s, ClinicalTrials.gov ~50/min, NCBI 3/s
  (10/s with a key).
- A 6-hour in-memory cache serves repeat queries.
- Tools return typed pydantic models, exposed as MCP structured output.
- Schemas were checked against Open Targets API 26.9 and mcp 2.3.0 (where FastMCP is named
  `MCPServer`). Open Targets removed `knownDrugs` and `yearOfFirstApproval`: this server uses
  `drugAndClinicalCandidates` and the `APPROVAL` clinical stage, and takes approval years from
  ChEMBL.
