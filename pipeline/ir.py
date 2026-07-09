"""Pipeline intermediate representation (IR) — the token stream modules pass along.

This is deliberately **not** in `schemas/`. `schemas/` holds the external, human-owned
contracts (ground truth, extraction output, the claim graph the API returns). The IR here
is the pipeline's private working format: the words + boxes M1 produces, which M2 segments,
M3 extracts from, and M3.5 grounds against. Keeping it in `pipeline/` means evolving the
internal representation never touches a public contract.

Coordinates are normalized to 0..1 (origin top-left) via `schemas.common.BBox`, so evidence
is resolution-independent (a token's box means the same thing on the 300-DPI render and in
the dashboard's rescaled view).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from schemas.common import BBox


class Token(BaseModel):
    """One word with its position on a page."""

    text: str
    bbox: BBox
    page: int = Field(ge=0, description="0-based page index within the claim file")
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0,
        description="1.0 for a digital text layer; per-word OCR confidence for scans",
    )


class PageIR(BaseModel):
    """One physical page after ingest: its text layer, tokens, and quality signals."""

    page: int = Field(ge=0)
    width: float = Field(gt=0, description="page width in PDF points")
    height: float = Field(gt=0, description="page height in PDF points")
    is_digital: bool = Field(description="text pulled from the PDF layer vs OCR'd from a scan")
    readability: float = Field(ge=0.0, le=1.0, description="M1 quality-gate score")
    unreadable: bool = False
    text: str = Field(default="", description="full page text in reading order")
    tokens: list[Token] = Field(default_factory=list)

    def line_texts(self) -> list[str]:
        """Tokens regrouped into visual lines (by y-band), left-to-right. Handy for the
        label→value parsing M3 does without re-reading the PDF."""
        if not self.tokens:
            return [ln for ln in self.text.splitlines() if ln.strip()]
        rows: list[tuple[float, list[Token]]] = []
        for tok in sorted(self.tokens, key=lambda t: (t.bbox.y0, t.bbox.x0)):
            cy = (tok.bbox.y0 + tok.bbox.y1) / 2
            for y, row in rows:
                if abs(cy - y) < 0.010:  # same visual line (~1% of page height)
                    row.append(tok)
                    break
            else:
                rows.append((cy, [tok]))
        return [
            " ".join(t.text for t in sorted(row, key=lambda t: t.bbox.x0))
            for _, row in rows
        ]


class ClaimIR(BaseModel):
    """Every page of one uploaded claim file, post-ingest."""

    claim_id: str
    source_pdf: str
    pages: list[PageIR] = Field(default_factory=list)

    @property
    def readable_pages(self) -> list[PageIR]:
        return [p for p in self.pages if not p.unreadable]
