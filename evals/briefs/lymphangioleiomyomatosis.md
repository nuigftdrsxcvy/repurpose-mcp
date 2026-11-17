<!--
Provenance: generated 2026-11-17 by Claude Code (Claude Opus 5.5) calling the repurpose-mcp tools
(find_disease, disease_targets, approved_drugs_for_targets, existing_trials, literature) and
following the repurposing_brief prompt. Kept as the sample input for evals/run.py citation checks.
-->

# Repurposing evidence brief: lymphangioleiomyomatosis

**Disease:** lymphangioleiomyomatosis (MONDO_0011705). Alternatives considered: lung lymphangioleiomyomatosis (MONDO_0006277), PEComa (MONDO_0006359).
**Date:** 2026-11-17 · **Open Targets data:** 26.09 · Top 20 targets; 125 approved drugs act on them (first 50 reviewed).

| Drug | Target | Mechanism | Approval year | Off-patent heuristic | Trials | PMIDs | Evidence strength | Gaps |
|---|---|---|---|---|---|---|---|---|
| EVEROLIMUS (CHEMBL1908360) | FKBP1A (ENSG00000088832, 0.53) | FK506-binding protein 1A inhibitor [INHIBITOR] | 2009 (ChEMBL) | unlikely (heuristic) | NCT01059318 (Ph2, completed, n=24); NCT00790400 (Ph3, completed, n=118, angiomyolipoma in TSC or sporadic LAM); NCT00457964 (Ph1/2, completed, n=36) | none found | Moderate | No results publication retrieved for the LAM trials. The Ph3 trial's primary population is angiomyolipoma. FKBP1A's LAM association is entirely clinical-datatype evidence. Under 20 years since approval. |
| TEMSIROLIMUS (CHEMBL1201182) | FKBP1A (ENSG00000088832, 0.53) | FK506-binding protein 1A inhibitor [INHIBITOR] | 2007 (ChEMBL) | unlikely (heuristic) | none found | PMID:21263090 | Weak | Single case-level report. The trial search returned sirolimus trials through synonym matching; none tested temsirolimus in LAM, so none are cited. IV-only formulation. |
| IMATINIB (CHEMBL941) | PDGFRB (ENSG00000113721, 0.10); ABL1 (ENSG00000097007, 0.09) | Tyrosine-protein kinase ABL inhibitor; PDGFR-beta inhibitor [INHIBITOR] | 2001 (ChEMBL, mesylate form CHEMBL1642) | likely (heuristic) | NCT03131999 (Ph1/2, completed, n=18); NCT06889168 (Ph1, recruiting, n=20 est.) | none found | Weak | Downgraded from Moderate: pilot with n<20. No published LAM results retrieved. Weak target association (0.10/0.09). |
| NINTEDANIB (CHEMBL502835) | PDGFRB (ENSG00000113721, 0.10); FGFR4, FLT4, FGFR2 | PDGFR inhibitor; VEGFR inhibitor; FGFR inhibitor [INHIBITOR] | 2014 (ChEMBL, esylate form CHEMBL3039504) | unlikely (heuristic) | NCT03062943 (Ph2, completed, n=30) | PMID:39489895 | Moderate | Downgraded from Strong: single-arm, open-label (per publication title). No randomised comparison with sirolimus. Under 20 years since approval. |
| CELECOXIB (CHEMBL118) | PTGS2 (ENSG00000073756, 0.09) | Cyclooxygenase-2 inhibitor [INHIBITOR] | 1998 (ChEMBL) | likely (heuristic) | NCT02484664 (Ph2, completed, n=12) | PMID:32060062 | Weak | Downgraded from Moderate: 12-participant pilot; the publication reports a phase I trial. Weak target association (0.09). Cardiovascular/GI safety in long-term use is not assessed here. |

### Already approved for this disease
- **SIROLIMUS (CHEMBL413)**: MONDO_0011705 is in its approved indications. First approval 1999 (ChEMBL); likely off-patent (heuristic). Supporting records: NCT00414648 (Ph3, completed, n=89); PMID:31429781 (long-term efficacy and safety).

### Notable exclusions
- **TACROLIMUS (CHEMBL269732) and PIMECROLIMUS (CHEMBL1200686)** share the FKBP1A mechanism annotation. However, FKBP1A's LAM association (ENSG00000088832) is entirely clinical-datatype evidence inherited from rapalog trials, so a shared FKBP1A annotation does not imply the same downstream pathway. No LAM trials were found for either. *Reviewer to verify: both are calcineurin inhibitors, not mTOR inhibitors.*
- **PERHEXILINE (CHEMBL75880)**: lists an mTOR inhibitor mechanism (MTOR, ENSG00000198793), but its ChEMBL withdrawn flag is set and no LAM trials or publications were found.
- **ZOTAROLIMUS (CHEMBL219410), RIDAFOROLIMUS (CHEMBL2103839)**: no first-approval year in ChEMBL; no LAM records searched.
- The remaining candidates (multikinase and COX inhibitors on PDGFRB, FLT4, FGFR2/4, SRC, ABL1 and PTGS2) were not searched individually: mechanistic only.

### Limitations
- Open Targets association scores measure target-disease evidence, not drug efficacy. Here FKBP1A ranks third only because of existing sirolimus/everolimus clinical evidence.
- The off-patent flag is a heuristic based on first approval year. Check the Orange Book or Purple Book, or the national equivalent.
- Searches can miss evidence (e.g. drugs acting downstream of TSC1/TSC2 rather than on an associated target) and can return irrelevant records.
- This is hypothesis generation, not clinical advice.
