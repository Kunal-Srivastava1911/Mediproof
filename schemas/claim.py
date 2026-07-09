"""The runtime claim graph — the object the API returns and the dashboard renders.

This is assembled by the pipeline: M1 fills `pages`, M2 fills `documents` boundaries and
types, M3 fills each document's `extracted`, M4 fills `findings`, M5 fills `completeness`.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from schemas.common import DocType
from schemas.documents import ExtractedDocument
from schemas.findings import Finding


class ClaimStatus(str, Enum):
    received = "received"
    processing = "processing"
    processed = "processed"
    needs_review = "needs_review"
    failed = "failed"


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
    at: datetime = Field(default_factory=datetime.utcnow)


class ClaimFile(BaseModel):
    """Top-level claim graph."""

    claim_id: str
    status: ClaimStatus = ClaimStatus.received
    created_at: datetime = Field(default_factory=datetime.utcnow)
    pages: list[PageInfo] = Field(default_factory=list)
    documents: list[DocumentRecord] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    completeness: CompletenessReport | None = None
    corrections: list[Correction] = Field(default_factory=list)
