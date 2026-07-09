# M1 — Ingest & Preprocess

**In:** an uploaded claim PDF. **Out:** the pipeline IR (`pipeline/ir.py`) — per page: words +
normalized boxes, full text, and a readability score — plus a projection to the public
`PageInfo` contract (`schemas/claim.py`).

## What's implemented (digital path)

Our synthetic claim PDFs carry a real text layer, so `ingest_pdf` reads words + exact
bounding boxes directly with **pdfplumber** — no OCR, fully deterministic.

- **Watermark masking (plan §5).** The diagonal `SPECIMEN` watermark is dropped *before*
  word-grouping. pdfplumber reports the ~30°-rotated glyphs as `upright`, so we detect
  rotation from the glyph matrix (`is_rotated_char`) instead — otherwise the watermark
  shatters into ~20 stray single-letter tokens that pollute extraction.
- **Quality gate.** `page_readability(n_words, mean_conf)` combines text coverage and mean
  token confidence (1.0 for a digital layer). Below `QUALITY_THRESHOLD` (0.40) a page is
  `unreadable=True`, excluded from auto-accept, and surfaced for re-upload — *garbage in
  must not become confident garbage out*.

## Scanned path (documented upgrade)

A page with no usable text layer needs the OpenCV-preprocess + PaddleOCR route (plan §M1).
That isn't wired into this build, so such a page is honestly marked `unreadable` (readability
0) rather than silently guessed. `Token.confidence` already carries per-word OCR confidence
for when that path lands.

## API

```python
from pipeline.m1_ingest import ingest_pdf, page_infos
ir = ingest_pdf("data/sample/claim.pdf")     # -> ClaimIR (pages -> tokens + boxes)
pages = page_infos(ir)                        # -> list[PageInfo] for the claim graph
```

Run `make test-m1`.
