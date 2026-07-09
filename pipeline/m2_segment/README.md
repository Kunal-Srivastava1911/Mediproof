# M2 — Segmentation & Classification (W3)

**In:** pages + OCR text. **Out:** `list[DocumentRecord]` (doc_type + page_range +
classifier_confidence).

Classify each page over the 9 `DocType` classes, then split the page stream into documents
at class-change + first-page cues (letterheads, doc titles).

**Staged (build cheapest first):**
- **P0** keyword/heuristic on OCR text — a floor.
- **P1** text-embedding classifier (sentence-transformers) — cheap, no GPU.
- **P2** LayoutLMv3-base + LoRA — *only if P1 < 92%* on the unseen-template dev split.

**DoD:** classification accuracy ≥ 90% on unseen-template dev split (else schedule P2);
segmentation boundary F1 reported via `make eval`.
