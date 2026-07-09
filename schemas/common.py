"""Shared contract primitives for MediProof.

`schemas/` is the single source of truth (see CLAUDE.md). Every module imports from
here; nothing here imports from a pipeline module.
"""

from __future__ import annotations

from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, Field


class DocType(str, Enum):
    """The nine document classes MediProof segments a claim file into."""

    discharge_summary = "discharge_summary"
    hospital_bill = "hospital_bill"
    pharmacy_bill = "pharmacy_bill"
    lab_report = "lab_report"
    prescription = "prescription"
    claim_form = "claim_form"
    id_document = "id_document"
    pre_auth = "pre_auth"
    other = "other"


class Gender(str, Enum):
    male = "M"
    female = "F"
    other = "O"


class Severity(str, Enum):
    """Audit finding severity. Deliberately not a fraud scale — see CLAUDE.md framing."""

    info = "info"
    warning = "warning"
    critical = "critical"


class FieldSource(str, Enum):
    """How an extracted value was produced (drives confidence fusion in M3)."""

    rule = "rule"
    llm = "llm"
    fusion = "fusion"
    none = "none"


class ConfidenceBand(str, Enum):
    green = "green"   # >= 0.8  auto-accept
    amber = "amber"   # 0.5–0.8 review queue
    red = "red"       # < 0.5   mandatory review


# Confidence thresholds (plan §M3). Calibrated on a held-out split in W8.
GREEN_THRESHOLD = 0.8
AMBER_THRESHOLD = 0.5


def band_for(confidence: float) -> ConfidenceBand:
    """Map a confidence score in [0,1] to its review band."""
    if confidence >= GREEN_THRESHOLD:
        return ConfidenceBand.green
    if confidence >= AMBER_THRESHOLD:
        return ConfidenceBand.amber
    return ConfidenceBand.red


class BBox(BaseModel):
    """Axis-aligned box in normalized page coordinates (0..1), origin top-left.

    Normalized so evidence is resolution-independent across the 300-DPI render and any
    re-scaled dashboard view.
    """

    x0: float = Field(ge=0.0, le=1.0)
    y0: float = Field(ge=0.0, le=1.0)
    x1: float = Field(ge=0.0, le=1.0)
    y1: float = Field(ge=0.0, le=1.0)


class Evidence(BaseModel):
    """A pointer from an extracted value (or finding) back to where it lives on a page."""

    page: int = Field(ge=0, description="0-based page index within the claim file")
    bbox: BBox
    ocr_confidence: float | None = Field(
        default=None, ge=0.0, le=1.0, description="mean OCR confidence of source tokens"
    )


T = TypeVar("T")


class ExtractedField(BaseModel, Generic[T]):
    """A single extracted value carrying its confidence and grounding.

    This is the atom the HITL dashboard renders: a value, a colour band, and the
    click-to-highlight evidence. `value=None, confidence=0.0` is the well-defined
    "could not extract" state the pipeline emits instead of crashing.
    """

    value: T | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source: FieldSource = FieldSource.none
    evidence: list[Evidence] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)

    @property
    def band(self) -> ConfidenceBand:
        return band_for(self.confidence)


class Money(BaseModel):
    """A monetary amount. INR, rupees to two decimals for synthetic data."""

    amount: float = Field(ge=0.0)
    currency: str = "INR"
