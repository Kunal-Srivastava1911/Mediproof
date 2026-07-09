"""Service layer: run the pipeline and apply reviewer corrections to a claim graph."""

from __future__ import annotations

from datetime import date, datetime

from schemas.claim import ClaimFile, Correction
from schemas.common import ExtractedField, FieldSource


def _coerce(new_value: str, like) -> object:
    """Coerce a reviewer's string edit to the existing value's type."""
    if isinstance(like, bool):
        return new_value.strip().lower() in ("true", "1", "yes")
    if isinstance(like, int) and not isinstance(like, bool):
        try:
            return int(new_value)
        except ValueError:
            return like
    if isinstance(like, float):
        try:
            return round(float(new_value), 2)
        except ValueError:
            return like
    if isinstance(like, date):
        for fmt in ("%Y-%m-%d", "%d %b %Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(new_value, fmt).date()
            except ValueError:
                continue
        return like
    return new_value


def _resolve_field(extracted, field_path: str) -> ExtractedField | None:
    obj = extracted
    for part in field_path.split("."):
        if part.isdigit():
            idx = int(part)
            if not isinstance(obj, list) or idx >= len(obj):
                return None
            obj = obj[idx]
        else:
            obj = getattr(obj, part, None)
        if obj is None:
            return None
    return obj if isinstance(obj, ExtractedField) else None


def apply_correction(claim: ClaimFile, correction: Correction) -> Correction:
    """Apply one HITL correction to the claim graph in place; returns the logged correction.

    The corrected field is marked human-verified (confidence 1.0) and its prior value recorded.
    """
    doc = next((d for d in claim.documents if d.document_id == correction.document_id), None)
    if doc is None or doc.extracted is None:
        raise KeyError(f"document {correction.document_id} not found")
    field = _resolve_field(doc.extracted, correction.field_path)
    if field is None:
        raise KeyError(f"field {correction.field_path} not found")

    old = field.value
    field.value = _coerce(correction.new_value or "", old)
    field.confidence = 1.0
    field.source = FieldSource.fusion
    if "reviewer_corrected" not in field.flags:
        field.flags.append("reviewer_corrected")

    logged = Correction(
        document_id=correction.document_id, field_path=correction.field_path,
        old_value=str(old) if old is not None else None,
        new_value=str(field.value), reviewer=correction.reviewer,
    )
    claim.corrections.append(logged)
    return logged
