# M2 — Segmentation + Classification

**In:** `ClaimIR` (M1 pages + tokens). **Out:** `list[DocumentRecord]` — typed documents with
their page ranges and a classifier confidence (for the claim graph).

## What's implemented — the P0 baseline (plan §M2)

A transparent **keyword/heuristic classifier** over each page's text (`DOC_KEYWORDS`): document
titles carry the most weight, body-field cues break ties. Cheap, no GPU, fully explainable —
the floor the plan says to build first.

- `classify_page(page) -> (DocType, confidence)` — confidence blends the winner's share of
  matched weight with its margin over the runner-up; a matched title cue floors it green.
- `segment_claim(claim_ir)` — boundary detection: a new document starts on a class change or a
  first-page cue (letterhead title), so multi-page documents stay whole. Unreadable pages
  (M1 quality gate) are excluded, never silently classified.

## Staged upgrades (same interface, behind metrics — plan §M2)

- **P1** — sentence-transformer embeddings over page text (no GPU).
- **P2** — LayoutLMv3-base + LoRA on synthetic pages, *only if P1 < 92%* on the unseen-template
  dev split.

Both drop in behind `classify_page` without touching M1 or M3.

## API

```python
from pipeline.m2_segment import segment_claim
docs = segment_claim(ir)   # -> [DocumentRecord(doc_type=..., page_range=[...], confidence=...)]
```

**DoD:** classification accuracy ≥ 90% on the unseen-template dev split (reported by
`make eval`); segmentation boundary F1 reported there too. Run `make test-m2`.
