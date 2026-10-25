"""Audit-finding contracts (M4 cross-document audit, M5 completeness).

Framing rule (non-negotiable, see CLAUDE.md): findings are *documentation review items*,
never accusations. No "fraud"/"reject" language anywhere.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from schemas.common import Evidence, Severity


class FindingType(str, Enum):
    """Stable ids for the rule pack. Ground-truth fault labels reference these so the
    eval harness can score precision/recall per fault type."""

    name_inconsistent = "name_inconsistent"
    age_gender_inconsistent = "age_gender_inconsistent"
    date_inconsistent = "date_inconsistent"
    bill_arithmetic_mismatch = "bill_arithmetic_mismatch"
    duplicate_line_item = "duplicate_line_item"
    inflated_line_item = "inflated_line_item"
    unmatched_medication = "unmatched_medication"
    prescription_pharmacy_mismatch = "prescription_pharmacy_mismatch"
    missing_lab_report = "missing_lab_report"
    drug_diagnosis_implausible = "drug_diagnosis_implausible"
    non_payable_consumable = "non_payable_consumable"
    missing_document = "missing_document"
    tampering_signal = "tampering_signal"
    # Cross-document semantic/temporal checks (the agent auditor, plus the rules that cover
    # the "seen" fault families of these kinds).
    temporal_inconsistency = "temporal_inconsistency"
    unsupported_by_documentation = "unsupported_by_documentation"
    missing_report = "missing_report"
    cross_document_contradiction = "cross_document_contradiction"


class FindingOrigin(str, Enum):
    """Who raised a review item."""

    rule = "rule"          # deterministic YAML rule pack
    agent = "agent"        # an LLM specialist agent, then verified (see `verified_by`)
    reviewer = "reviewer"  # a held-back agent item a human promoted


class FindingDecision(str, Enum):
    """The reviewer's per-item decision (logged as verifier training data)."""

    open = "open"
    confirmed = "confirmed"
    dismissed = "dismissed"


class ProofQuote(BaseModel):
    """A verbatim quote an agent cites as evidence, and where it was found on the page.

    An agent finding is *proof-carrying*: every quote must be located on the cited
    document's page tokens (`grounded`) or the finding cannot pass verification.
    """

    document_id: str
    quote: str
    grounded: bool = False
    evidence: list[Evidence] = Field(default_factory=list)


class Finding(BaseModel):
    """One review item produced by the audit engine.

    `evidence` links every finding to its bbox(es) so a human can judge it — this is what
    keeps a finding a review item rather than an accusation.
    """

    id: str = Field(description="unique id within a claim, e.g. 'F-003'")
    type: FindingType
    severity: Severity
    title: str = Field(description="short reviewer-facing label, review-item language only")
    detail: str = Field(description="what was observed and why it needs review")
    evidence: list[Evidence] = Field(default_factory=list)
    document_ids: list[str] = Field(
        default_factory=list, description="ids of documents this finding spans"
    )
    rule_id: str | None = Field(default=None, description="id of the YAML rule that fired")

    origin: FindingOrigin = FindingOrigin.rule
    agent: str | None = Field(default=None, description="specialist agent that proposed it")
    proof: list[ProofQuote] = Field(default_factory=list)
    verified_by: list[str] = Field(
        default_factory=list, description="checks it passed, e.g. 'grounding', 'code check', "
                                          "'skeptic agent'")
    verifier_score: float | None = Field(default=None, ge=0.0, le=1.0)
    held_back: bool = Field(
        default=False, description="scored below the calibrated threshold: shown to reviewers "
                                   "only, never to the patient")
    patient_facing: bool = Field(
        default=True, description="false for reviewer-only items (e.g. payability notes)")
    trail: list[str] = Field(default_factory=list, description="how the item was found")
    decision: FindingDecision = FindingDecision.open
    decision_reason: str | None = None
