# M1 — Ingest & Preprocess (W3)

**In:** uploaded PDF / images. **Out:** `list[PageInfo]` (see `schemas/claim.py`) + OCR
words/boxes per page.

- Split PDF to 300-DPI page images; OpenCV deskew/denoise/orientation/contrast.
- Detect digital PDF (text layer) vs scanned (OCR path); PaddleOCR → words + boxes + conf.
- **Quality gate:** per-page readability = f(Laplacian blur variance, contrast, OCR mean
  conf). Below threshold → `unreadable=True`, excluded from auto-accept, surfaced for
  re-upload. Garbage in must not become confident garbage out.

**DoD:** golden tests green on fixture pages; readability score computed per page.
