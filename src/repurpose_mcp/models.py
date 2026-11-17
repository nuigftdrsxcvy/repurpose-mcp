"""Typed tool return values. Every record carries the identifier and URL needed to verify it."""

from __future__ import annotations

from pydantic import BaseModel, Field

OFF_PATENT_HEURISTIC = (
    "HEURISTIC ONLY: likely_off_patent is true when the first approval year is at least "
    "{years} years before {today_year}. It is not a patent or exclusivity search. Formulation, "
    "use, and paediatric/orphan exclusivities can outlast the compound patent; biologics "
    "may have no biosimilar even when old; and the approval year may come from a "
    "fallback source that understates the drug's true age. Check the FDA Orange Book "
    "(small molecules), Purple Book (biologics) or the national equivalent before acting on it."
)

ASSOCIATION_SCORE_NOTE = (
    "Open Targets association scores (0-1) summarise how much evidence links a target to a "
    "disease (genetics, literature mining, animal models, prior clinical use, etc.). They are "
    "NOT evidence that modulating the target, or any drug, is effective in the disease. The "
    "'clinical' datatype reflects existing drug trials or approvals, so targets of drugs "
    "already tested in this disease score higher."
)


class DiseaseHit(BaseModel):
    id: str = Field(description="Open Targets disease ID (EFO/MONDO/Orphanet ontology term)")
    name: str
    description: str | None = None
    source_url: str


class FindDiseaseResult(BaseModel):
    query: str
    hits: list[DiseaseHit]
    source: str = "Open Targets Platform search"


class TargetAssociation(BaseModel):
    target_id: str = Field(description="Ensembl gene ID")
    symbol: str
    name: str
    overall_score: float
    datatype_scores: dict[str, float] = Field(description="Score per evidence datatype, 0-1")
    source_url: str


class DiseaseTargetsResult(BaseModel):
    disease_id: str
    disease_name: str
    total_associated_targets: int
    excluded_datasources: list[str] = Field(default_factory=list)
    targets: list[TargetAssociation]
    note: str = ASSOCIATION_SCORE_NOTE
    data_version: str | None = None


class Mechanism(BaseModel):
    mechanism_of_action: str
    action_type: str | None = None
    target_ids: list[str]


class Indication(BaseModel):
    disease_id: str
    disease_name: str


class ApprovedDrug(BaseModel):
    chembl_id: str
    name: str
    drug_type: str
    parent_chembl_id: str | None = Field(None, description="Parent molecule, when this is a salt or form")
    other_form_chembl_ids: list[str] = Field(
        default_factory=list, description="Salt/hydrate forms merged into this entry"
    )
    query_target_ids: list[str] = Field(description="Which of the requested targets this drug acts on")
    query_target_symbols: list[str]
    mechanisms: list[Mechanism]
    year_of_first_approval: int | None
    approval_year_source: str | None = Field(
        None, description="'ChEMBL first_approval' (possibly of a related salt/parent form) or an Open Targets fallback"
    )
    likely_off_patent: bool | None = Field(
        description="HEURISTIC: first approval >= 20 years ago. None when the approval year is unknown."
    )
    withdrawn_flag: bool | None = Field(None, description="ChEMBL withdrawn flag (withdrawn in at least one country)")
    approved_indications: list[Indication]
    source_url: str


class ApprovedDrugsResult(BaseModel):
    target_ids: list[str]
    unknown_target_ids: list[str] = Field(default_factory=list)
    total_approved_drugs: int
    truncated: bool = Field(description="True if more approved drugs exist than were returned (raise max_drugs)")
    drugs: list[ApprovedDrug]
    warnings: list[str] = Field(default_factory=list)
    off_patent_heuristic: str
    data_version: str | None = None


class Trial(BaseModel):
    nct_id: str
    title: str
    phases: list[str]
    status: str | None
    enrollment: int | None
    enrollment_type: str | None = Field(None, description="ACTUAL or ESTIMATED")
    start_date: str | None = None
    url: str


class TrialsResult(BaseModel):
    drug: str
    disease: str
    total_count: int
    trials: list[Trial]
    query_url: str
    note: str = (
        "ClinicalTrials.gov search matches condition and intervention terms, including synonyms. "
        "Check each record: a match does not guarantee the trial tests this drug for this disease."
    )


class Article(BaseModel):
    pmid: str
    title: str
    year: int | None
    journal: str | None = None
    url: str


class LiteratureResult(BaseModel):
    drug: str
    disease: str
    query: str
    query_translation: str | None = None
    total_count: int
    articles: list[Article]
    note: str = (
        "PubMed relevance search. A result can mention both terms without testing the drug in the "
        "disease; read titles before citing them as evidence."
    )
