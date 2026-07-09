# M3 — Hybrid Extraction + M3.5 Value Grounding (W4–W5)

**In:** a `DocumentRecord` + its pages/OCR. **Out:** the matching `Extracted*` model
(`schemas/documents.py`), every field carrying confidence + bbox evidence.

## Two layers
- **Deterministic (W4):** regex + validators — line items sum to totals; admission <
  discharge; pharmacy dates in-window; ICD-10 format; lab units + reference ranges.
- **LLM fallback (W5):** Gemini Flash / Claude Haiku with page image + OCR text, only for
  fields the deterministic layer can't fill or fills with low confidence.

## Confidence fusion (per field, ∈ [0,1])
- rule + validator pass → 0.95 × mean OCR word conf.
- LLM → self-consistency k=3: 3/3 → 0.85, 2/3 → 0.6, else 0.3; validator ±0.1.
- rule & LLM agree → max+0.05; conflict → 0.25 and auto-flag for HITL.
- bands: ≥0.8 green, 0.5–0.8 amber, <0.5 red (`schemas.common.band_for`).

## LLM client contract
All calls go through `llm_client.py`: **record/replay** to `tests/fixtures/llm/`
(deterministic, free, fast; live only when `LLM_LIVE=1`), **budget cap** `LLM_BUDGET_USD`,
and a **validated retry** — reply must parse into the field's Pydantic schema; on failure
retry with error feedback (max 2), then emit `value=null, confidence=0`. The pipeline never
crashes on a malformed LLM reply.

## M3.5 Value Grounding
Fuzzy-match each extracted value against OCR tokens on the source page (normalized
Levenshtein over token n-grams) to recover `{page, bbox}`. No grounding → confidence capped
at 0.5 and flagged. This is what makes click-to-highlight and evidence refs work.

**DoD:** end-to-end JSON for a full claim; every field carries confidence + bbox or a flag.
