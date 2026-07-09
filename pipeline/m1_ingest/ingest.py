"""M1 — Ingest & Preprocess.

Turns an uploaded claim PDF into the pipeline IR: per page, the words + normalized boxes,
a full-text reading, and a readability score (the quality gate).

**Digital path (implemented).** Our synthetic claim PDFs carry a real text layer, so we read
words + boxes directly with pdfplumber — no OCR, fully deterministic, and the boxes are exact
rather than estimated. The rotated `SPECIMEN` watermark is masked out here (plan §5: the
watermark region must not pollute extraction) by dropping non-upright tokens.

**Scanned path (upgrade hook).** A page with no usable text layer needs the OpenCV-preprocess
+ PaddleOCR route from plan §M1. That isn't wired into this build, so such a page is honestly
marked `unreadable` (readability 0) and surfaced for re-upload rather than silently guessed —
"garbage in must not become confident garbage out" (plan §M1 quality gate).
"""

from __future__ import annotations

import math
from pathlib import Path

import pdfplumber

from pipeline.ir import ClaimIR, PageIR, Token
from schemas.claim import PageInfo
from schemas.common import BBox

# Below this readability a page is excluded from auto-accept and surfaced for re-upload.
QUALITY_THRESHOLD = 0.40
# A page needs at least this many content words to count as a usable digital text layer.
MIN_CONTENT_WORDS = 3
# A char rotated past this angle is treated as watermark, not content (plan §5). pdfplumber
# calls the ~30° SPECIMEN watermark "upright", so we detect rotation from the glyph matrix.
_ROTATION_TOLERANCE_RAD = math.radians(5)


def _clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def is_rotated_char(char: dict) -> bool:
    """True if a pdfplumber char glyph is rotated (the diagonal SPECIMEN watermark)."""
    m = char.get("matrix")
    if not m:
        return False
    a, b = m[0], m[1]
    return abs(math.atan2(b, a)) > _ROTATION_TOLERANCE_RAD


def page_readability(n_words: int, mean_conf: float) -> float:
    """Quality-gate score from word coverage and mean token confidence.

    Coverage saturates around a page's worth of text (~20 words); confidence is 1.0 for a
    digital text layer and the OCR word confidence otherwise. A sparse or low-confidence page
    scores low and is routed to human re-upload.
    """
    coverage = min(1.0, n_words / 20.0)
    return round(_clamp01(mean_conf * (0.6 + 0.4 * coverage)), 4)


def _ingest_page(pdf_page, index: int) -> PageIR:
    w, h = float(pdf_page.width), float(pdf_page.height)
    # Mask the rotated SPECIMEN watermark before word-grouping (plan §5): drop rotated glyphs
    # so they don't leak in as scattered single-char tokens.
    unmarked = pdf_page.filter(
        lambda o: not (o.get("object_type") == "char" and is_rotated_char(o))
    )
    content = unmarked.extract_words(use_text_flow=False, keep_blank_chars=False)

    if len(content) < MIN_CONTENT_WORDS:
        # No usable text layer: this is the scanned/blurred case OCR would handle.
        return PageIR(page=index, width=w, height=h, is_digital=False,
                      readability=0.0, unreadable=True, text="", tokens=[])

    tokens = [
        Token(
            text=wd["text"],
            page=index,
            confidence=1.0,  # digital text layer is exact
            bbox=BBox(
                x0=_clamp01(wd["x0"] / w), y0=_clamp01(wd["top"] / h),
                x1=_clamp01(wd["x1"] / w), y1=_clamp01(wd["bottom"] / h),
            ),
        )
        for wd in content
    ]
    mean_conf = sum(t.confidence for t in tokens) / len(tokens)
    readability = page_readability(len(tokens), mean_conf)
    page = PageIR(
        page=index, width=w, height=h, is_digital=True,
        readability=readability, unreadable=readability < QUALITY_THRESHOLD, tokens=tokens,
    )
    page.text = "\n".join(page.line_texts())
    return page


def ingest_pdf(pdf_path: str | Path, claim_id: str | None = None) -> ClaimIR:
    """Read a claim PDF into the pipeline IR (words + boxes + quality per page)."""
    pdf_path = Path(pdf_path)
    claim_id = claim_id or pdf_path.stem
    pages: list[PageIR] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for i, pdf_page in enumerate(pdf.pages):
            pages.append(_ingest_page(pdf_page, i))
    return ClaimIR(claim_id=claim_id, source_pdf=str(pdf_path), pages=pages)


def page_infos(claim_ir: ClaimIR) -> list[PageInfo]:
    """Project the IR down to the public `PageInfo` contract (for the claim graph / API)."""
    return [
        PageInfo(
            page=p.page, width=int(p.width), height=int(p.height),
            is_digital=p.is_digital, readability=p.readability, unreadable=p.unreadable,
        )
        for p in claim_ir.pages
    ]
