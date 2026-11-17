# repurpose-mcp evaluation results

Run: 2026-11-17 17:12 · command: `python evals/run.py `

Open Targets API 26.9.0, data release 26.09.

## (a) Citation integrity

A citation **passes** when the record exists and its text (PubMed: title, abstract, MeSH, substances, keywords; ClinicalTrials.gov: titles, summary, conditions, interventions, MeSH) mentions both the drug of its table row and the disease. Drug terms: name, trade names and curated ChEMBL synonyms. Disease terms: Open Targets name plus exact, narrow and related synonyms (short abbreviations excluded). Citations outside the evidence table are checked for existence and disease mention only.

**Overall pass rate: 12/12 (100%)**

| Brief | Disease | Table rows | PMIDs pass | NCTs pass | Outside-table pass | Not found | Drug not mentioned | Disease not mentioned |
|---|---|---|---|---|---|---|---|---|
| `lymphangioleiomyomatosis.md` | lymphangioleiomyomatosis (MONDO_0011705) | 5 | 3/3 (100%) | 7/7 (100%) | 2/2 (100%) | 0 | 0 | 0 |

### `lymphangioleiomyomatosis.md`: every citation

| Result | ID | Cited for drug | Exists | Drug term matched | Disease term matched | Record title |
|---|---|---|---|---|---|---|
| PASS | NCT01059318 | EVEROLIMUS | yes | EVEROLIMUS | lymphangioleiomyomatosis | A Study to Determine the Safety and Effectiveness of RAD001 (Everolimus) in Patients With Lymphangioleiomyomatosis |
| PASS | NCT00790400 | EVEROLIMUS | yes | EVEROLIMUS | lymphangioleiomyomatosis | Efficacy and Safety of RAD001 in Patients Aged 18 and Over With Angiomyolipoma Associated With Either Tuberous Sclerosis |
| PASS | NCT00457964 | EVEROLIMUS | yes | EVEROLIMUS | lymphangioleiomyomatosis | RAD001 Therapy of Angiomyolipomata in Patients With TS Complex and Sporadic LAM |
| PASS | PMID:21263090 | TEMSIROLIMUS | yes | TEMSIROLIMUS | lymphangioleiomyomatosis | Response of lymphangioleiomyomatosis to a mammalian target of rapamycin inhibitor (temsirolimus) -based treatment. |
| PASS | NCT03131999 | IMATINIB | yes | IMATINIB MESYLATE | lymphangioleiomyomatosis | LAM Pilot Study With Imatinib Mesylate |
| PASS | NCT06889168 | IMATINIB | yes | IMATINIB MESYLATE | lymphangioleiomyomatosis | Evaluating the Long-term Safety and Tolerability of Imatinib in Patients With Lymphangioleiomyomatosis (LAM) |
| PASS | NCT03062943 | NINTEDANIB | yes | NINTEDANIB | lymphangioleiomyomatosis | A Study of Nintedanib for LymphAngioleioMyomatosis (LAM) |
| PASS | PMID:39489895 | NINTEDANIB | yes | NINTEDANIB | lymphangioleiomyomatosis | Nintedanib for patients with lymphangioleiomyomatosis: a phase 2, open-label, single-arm study. |
| PASS | NCT02484664 | CELECOXIB | yes | CELECOXIB | lymphangioleiomyomatosis | COLA: A Pilot Clinical Trial of COX-2 Inhibition in LAM and TSC |
| PASS | PMID:32060062 | CELECOXIB | yes | CELECOXIB | lymphangioleiomyomatosis | Celecoxib in lymphangioleiomyomatosis: results of a phase I clinical trial. |
| PASS | NCT00414648 | _(outside table)_ | yes | n/a | lymphangioleiomyomatosis | Efficacy and Safety of Sirolimus in LAM |
| PASS | PMID:31429781 | _(outside table)_ | yes | n/a | lymphangioleiomyomatosis | Long-term efficacy and safety of sirolimus therapy in patients with lymphangioleiomyomatosis. |

## (b) Recall on known repurposing cases

Cases: `evals/known_cases.csv`. Pipeline: top 20 Open Targets targets -> all approved drugs on them -> ranked by the best association score among each drug's targets. A case is a hit if the expected drug is in the top 10.

- **default**: standard Open Targets association scores. These include the `clinical_precedence` datasource (drugs trialled or approved for the disease), so a known repurposing success can rank its own target highly. Treat it as an upper bound.
- **no_clinical**: the same with `clinical_precedence` zero-weighted, so only genetic, literature, pathway, animal-model etc. evidence ranks targets. This is closer to the real prospective use case.

- **Recall@10 (default): 4/7 (57%)**; found anywhere in candidate list: 6/7 (86%)
- **Recall@10 (no_clinical): 0/7 (0%)**; found anywhere in candidate list: 0/7 (0%)

| Disease (as given) | Resolved to | Expected drug | Rank (default) | Rank (no_clinical) | Hit@10 default / no_clinical | Via target | Candidates (default / no_clinical) | Notes |
|---|---|---|---|---|---|---|---|---|
| lymphangioleiomyomatosis | lymphangioleiomyomatosis (MONDO_0011705) | sirolimus (CHEMBL413) | 3 | not found | yes / no | FKBP1A (0.53) | 125 / 112 | Verified 2026-11-17. Transplant immunosuppressant (mTOR inhibitor) approved for LAM |
| infantile hemangioma | capillary hemangioma (MONDO_0002407) | propranolol | 43 | not found | no / no | ADRB1 (0.52) | 102 / 35 | Verified 2026-11-17. MONDO_0002407 is capillary hemangioma, which lists infantile hemangioma as a synonym. Pinned so the eval is deterministic |
| multiple myeloma | plasma cell myeloma (MONDO_0009693) | thalidomide | 3 | not found | yes / no | CRBN (0.71) | 91 / 17 | Verified 2026-11-17. Withdrawn sedative repurposed via anti-angiogenic/immunomodulatory activity |
| pulmonary arterial hypertension | pulmonary arterial hypertension (MONDO_0015924) | sildenafil | 25 | not found | no / no | PDE5A (0.61) | 38 / 40 | Verified 2026-11-17. PDE5 inhibitor first developed for angina, then ED |
| tuberous sclerosis | tuberous sclerosis (MONDO_0001734) | everolimus | 1 | not found | yes / no | FKBP1A (0.57) | 82 / 11 | Verified 2026-11-17. mTOR inhibitor first approved for transplant and oncology |
| hereditary hemorrhagic telangiectasia | hereditary hemorrhagic telangiectasia (MONDO_0019180) | pomalidomide | not found | not found | no / no | - | 109 / 15 | Verified 2026-11-17. Positive phase 2 RCT, not approved for HHT |
| Marfan syndrome | Marfan syndrome (MONDO_0007947) | losartan | 9 | not found | yes / no | AGTR1 (0.38) | 97 / 3 | Verified 2026-11-17. Plausible hypothesis that was tested; no difference vs atenolol in aortic root growth. Counts as a hit for hypothesis generation, not as a success |

Check the **Resolved to** column: cases without a `disease_id` use the top `find_disease` hit, which may not be the disease you meant.
