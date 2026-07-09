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
