# M3 — Hybrid Extraction + M3.5 Value Grounding

**In:** a `DocumentRecord` + its ingested pages (tokens). **Out:** the matching `Extracted*`
model (`schemas/documents.py`), every field carrying confidence + (after M3.5) bbox evidence.

## Two layers (hybrid)

- **Deterministic (`extract.py`) — implemented.** Regex + validators over the text layer,
  keyed to the datagen templates' stable structure. Fills essentially every field on our
  digital PDFs. Validators bump confidence to green when they pass: bill line math +
  subtotal/total reconciliation, admission < discharge date logic, ICD-10 code format.
- **LLM fallback (`fuse.py`) — implemented.** Hybrid routing: the LLM is asked **only** for
  fields the deterministic layer left empty or below the amber threshold — so it never
  touches what rules already nailed (the unit-economics argument). Each LLM value gets a
  k=3 self-consistency confidence, then is fused with any rule value.

## Confidence fusion (per field ∈ [0,1], `confidence.py`)

- rule + validator pass → **0.95** × mean OCR word conf; rule alone → 0.85.
- LLM self-consistency k=3: 3/3 → **0.85**, 2/3 → 0.60, else 0.30; validator ±0.10.
- rule & LLM **agree** → max+0.05; **conflict** → 0.25 and auto-flag `rule_llm_conflict`.
- bands: ≥0.8 green, 0.5–0.8 amber, <0.5 red (`schemas.common.band_for`).

## LLM client (`llm_client.py`)

Every call goes through one thin client — **Gemini** (`LLM_PROVIDER=gemini`, `google-genai`
SDK, default `gemini-3.5-flash-lite`, free tier: paced by `LLM_MIN_INTERVAL_S` and retried on 429)
or **Claude** (`LLM_PROVIDER=anthropic`, Anthropic SDK, default `claude-opus-5-5`):
**record/replay** to `tests/fixtures/llm/` (deterministic, free, offline; live only when
`LLM_LIVE=1` with `GEMINI_API_KEY` or `ANTHROPIC_API_KEY` set or in `.env`), a hard
**budget cap** `LLM_BUDGET_USD` checked
*before* each live call with spend booked from real token usage, structured JSON outputs
(`complete_json`, used by the M4 agents), server-side refusal fallback (`LLM_FALLBACKS`),
and graceful failure — a missing fixture or malformed reply degrades to
`value=None, confidence=0`. **The pipeline never crashes on the LLM.**

Live Gemini calls can't hang or stall for long:

- **Timeout** — each request is capped at `LLM_TIMEOUT_S` (default 90). A timeout is
  retried once; a second one raises `LLMError`, so the agent step ends with a note instead
  of leaving the claim stuck in `processing`.
- **Rate-limit waits** — on a per-minute 429 the client waits the `retryDelay` Google sends
  (+1s), capped at 120s; with no hint it falls back to 30s, then 60s. A daily-quota 429
  stops further calls for the run.
- **Progress log** — every live call logs start, duration, tokens and any wait on the
  `mediproof.llm` logger (shown in the API window; `LLM_LOG_LEVEL=DEBUG` adds pacing waits):

  ```
  11:31:02 [llm] gemini:gemini-3.8-flash call 8a8da61cd2203490 started (live call #1 this run)
  11:31:03 [llm] Gemini 429 (rate-limited); waiting 8s, retry 1/2
  11:31:22 [llm] reply: 3210 tokens in / 840 out (incl. 412 thinking)
  11:31:22 [llm] call 8a8da61cd2203490 done in 19.6s
  ```

## M3.5 Value Grounding (`grounding.py`) — implemented

Every extracted value is fuzzy-matched (rapidfuzz, normalized Levenshtein over token
n-grams) against the page's word tokens to recover `{page, bbox}` evidence. A value that
can't be grounded (match < 85) has its confidence **capped at 0.5** and is flagged
`ungrounded`. On a digital claim ≥ 90% of fields ground to an exact box — this is what makes
click-to-highlight and the audit report's evidence refs point at something real.

```python
from pipeline.m3_extract import extract_claim, ground_claim
recs = ground_claim(ir, extract_claim(ir, segment_claim(ir)))
# each Extracted* field now carries .evidence = [{page, bbox}]
```

**DoD:** end-to-end JSON for a full claim; every field carries confidence + bbox or a flag.
Run `make test-m3`.
