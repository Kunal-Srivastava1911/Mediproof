"""M3.5 — Value Grounding (plan §M3.5).

Extraction returns *values*, not coordinates. For every extracted field we fuzzy-match its
display string against the page's word tokens (normalized Levenshtein over token n-grams,
via rapidfuzz) to recover `{page, bbox}` evidence. No good match → confidence is capped and
the field flagged `ungrounded`.

This is what makes click-to-highlight, the audit report's evidence refs, and tampering
evidence actually point at something a human can look at.
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel
from rapidfuzz import fuzz

from pipeline.ir import ClaimIR, PageIR, Token
from schemas.claim import DocumentRecord
from schemas.common import BBox, Evidence, ExtractedField

# Minimum normalized match (0–100) to accept a grounding.
GROUND_THRESHOLD = 85.0
# A field we can't ground is capped here and flagged (plan §M3.5).
GROUNDING_CAP = 0.5
# Extra tokens beyond the value's own word count to allow in a match window.
_WINDOW_SLACK = 2


def _display(value) -> str:
    """Render an extracted value to the string as it appears on the page."""
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, date):
        return value.strftime("%d %b %Y")
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _rows(page: PageIR) -> list[list[Token]]:
    """Tokens grouped into visual lines (a value renders within one line)."""
    rows: list[tuple[float, list[Token]]] = []
    for tok in sorted(page.tokens, key=lambda t: (t.bbox.y0, t.bbox.x0)):
        cy = (tok.bbox.y0 + tok.bbox.y1) / 2
        for y, row in rows:
            if abs(cy - y) < 0.010:
                row.append(tok)
                break
        else:
            rows.append((cy, [tok]))
    return [sorted(r, key=lambda t: t.bbox.x0) for _, r in rows]


def _union(boxes: list[BBox]) -> BBox:
    return BBox(
        x0=min(b.x0 for b in boxes), y0=min(b.y0 for b in boxes),
        x1=max(b.x1 for b in boxes), y1=max(b.y1 for b in boxes),
    )


def _best_match(display: str, pages: list[PageIR]) -> tuple[float, int, BBox, float] | None:
    target = display.strip().lower()
    if not target:
        return None
    n = len(target.split())
    best: tuple[float, int, BBox, float] | None = None
    for page in pages:
        for row in _rows(page):
            for i in range(len(row)):
                for size in range(1, n + _WINDOW_SLACK + 1):
                    if i + size > len(row):
                        break
                    window = row[i:i + size]
                    text = " ".join(t.text for t in window).lower()
                    ratio = fuzz.ratio(target, text)
                    if best is None or ratio > best[0]:
                        bbox = _union([t.bbox for t in window])
                        oconf = sum(t.confidence for t in window) / len(window)
                        best = (ratio, page.page, bbox, oconf)
    return best


def ground_field(field: ExtractedField, pages: list[PageIR]) -> ExtractedField:
    """Attach `{page, bbox}` evidence to a field, or cap+flag it if it can't be grounded."""
    if field.value is None:
        return field
    match = _best_match(_display(field.value), pages)
    if match and match[0] >= GROUND_THRESHOLD:
        _, page, bbox, oconf = match
        field.evidence = [Evidence(page=page, bbox=bbox, ocr_confidence=round(oconf, 4))]
    else:
        field.confidence = round(min(field.confidence, GROUNDING_CAP), 4)
        if "ungrounded" not in field.flags:
            field.flags.append("ungrounded")
    return field


def _walk_fields(model: BaseModel):
    """Yield every `ExtractedField` inside a document model (recursing sub-models + lists)."""
    for value in vars(model).values():
        if isinstance(value, ExtractedField):
            yield value
        elif isinstance(value, BaseModel):
            yield from _walk_fields(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, ExtractedField):
                    yield item
                elif isinstance(item, BaseModel):
                    yield from _walk_fields(item)


def ground_document(extracted, pages: list[PageIR]):
    """Ground every field of one extracted document against its page tokens (in place)."""
    for field in _walk_fields(extracted):
        ground_field(field, pages)
    return extracted


def ground_claim(claim_ir: ClaimIR, records: list[DocumentRecord]) -> list[DocumentRecord]:
    """Ground every extracted field in every document of a claim (in place)."""
    by_page = {p.page: p for p in claim_ir.pages}
    for rec in records:
        if rec.extracted is None:
            continue
        pages = [by_page[pg] for pg in rec.page_range if pg in by_page]
        ground_document(rec.extracted, pages)
    return records
