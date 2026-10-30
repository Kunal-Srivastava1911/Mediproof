"""The runtime claim graph — the object the API returns and the dashboard renders.

This is assembled by the pipeline: M1 fills `pages`, M2 fills `documents` boundaries and
types, M3 fills each document's `extracted`, M4 fills `findings`, M5 fills `completeness`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from schemas.common import DocType
from schemas.documents import ExtractedDocument
from schemas.findings import Finding


def _utcnow() -> datetime:
    """Timezone-aware UTC now (SQLAlchemy 2.1+ rejects naive datetimes)."""
    return datetime.now(UTC)

class ClaimStatus(str, Enum):
    received = "received"
    processing = "processing"
    processed = "processed"
    needs_review = "needs_review"
    failed = "failed"
    approved = "approved"
    denied = "denied"


class PageInfo(BaseModel):
    """One physical page of the uploaded claim file (M1 output)."""

    page: int = Field(ge=0, description="0-based index in the merged file")
    width: int
    height: int
    is_digital: bool = Field(description="text extracted from PDF layer vs OCR'd from scan")
    readability: float = Field(ge=0.0, le=1.0, description="M1 quality-gate score")
    unreadable: bool = False
    image_path: str | None = None


class DocumentRecord(BaseModel):
    """A typed document spanning one or more pages (M2 segmentation output)."""

    document_id: str
    doc_type: DocType
    page_range: list[int] = Field(description="page indices belonging to this document")
    classifier_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    extracted: ExtractedDocument | None = Field(
        default=None, description="M3 hybrid-extraction output for this document"
    )


class CompletenessReport(BaseModel):
    """M5 output: required-docs checklist for the claim type."""

    claim_type: str
    required: list[DocType] = Field(default_factory=list)
    present: list[DocType] = Field(default_factory=list)
    missing: list[DocType] = Field(default_factory=list)


class Correction(BaseModel):
    """A HITL reviewer edit — stored as training data (plan §M6)."""

    document_id: str
    field_path: str = Field(description="dotted path, e.g. 'patient.name' or 'line_items.3.amount'")
    old_value: str | None = None
    new_value: str | None = None
    reviewer: str | None = None
    at: datetime = Field(default_factory=_utcnow)


class TimelineEvent(BaseModel):
    """One dated event read from one document, placed on the claim's shared timeline."""

    document_id: str
    doc_type: DocType
    label: str = Field(description="e.g. 'Admission', 'ICU stay', 'Pharmacy bill'")
    start: date
    end: date | None = Field(default=None, description="set for spans (stays)")
    conflict: bool = Field(default=False, description="disagrees with another document")
    finding_ids: list[str] = Field(default_factory=list)


class EvidenceCell(BaseModel):
    """One edge of the claim evidence graph: a fact as one document states it."""

    fact: str = Field(description="e.g. 'Patient name', 'Admission date'")
    document_id: str
    doc_type: DocType
    value: str
    status: Literal["agrees", "conflicts", "missing"] = "agrees"
    finding_ids: list[str] = Field(default_factory=list)


class AuditMeta(BaseModel):
    """What the audit engine ran for this claim (shown in the dashboard, used by evals)."""

    agents_run: list[str] = Field(default_factory=list)
    model: str | None = Field(default=None, description="provider:model that produced it")
    llm_calls: int = 0
    llm_cost_usd: float = 0.0
    verifier_threshold: float | None = None
    note: str | None = Field(default=None, description="e.g. why the agent auditor was skipped")


class ClaimFile(BaseModel):
    """Top-level claim graph."""

    claim_id: str
    status: ClaimStatus = ClaimStatus.received
    created_at: datetime = Field(default_factory=_utcnow)
    pages: list[PageInfo] = Field(default_factory=list)
    documents: list[DocumentRecord] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    completeness: CompletenessReport | None = None
    corrections: list[Correction] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    evidence_map: list[EvidenceCell] = Field(default_factory=list)
    audit: AuditMeta | None = None
