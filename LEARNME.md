# LEARNME.md — MediProof, taught topic by topic

This is a curriculum, not documentation. It's meant to be fed back to an AI assistant
(Claude) one topic at a time, so you build a real technical understanding of MediProof
deep enough to explain and defend it to your professor — not just recite the README.

## How to use this file

Copy this file into a conversation with Claude (or just reference it if Claude already
has repo access) and say something like:

> "Teach me Topic 2 from LEARNME.md in depth."

For each topic, ask Claude to:
1. **Explain the concept in isolation first** — what problem it solves and why it's
   needed, before touching this repo's code.
2. **Walk the actual code** at the file/function level (paths are given per topic).
3. **Show you the data** — run the relevant command and look at real output
   (`make datagen-sample`, `make eval`, or a `curl` against the running API).
4. **Stress-test your understanding** — ask it to quiz you or pose the kind of question
   a professor would ask (edge cases, "why not do X instead", failure modes).

Go roughly in order — later topics assume earlier ones. Budget ~30–45 min per topic if
you want to actually retain it, not skim it.

---

## Track A — Problem framing & data contracts

### Topic 1. The problem and why it's hard
What "claim documentation QA" means, why it's not the same as fraud detection or clinical
adjudication, and why a stack of hospital bill / discharge summary / pharmacy bill / lab
report / prescription is genuinely messy to reconcile automatically.
- Read first: [README.md](README.md) §"The problem, in one paragraph", [plan.md](plan.md) §1–2
- Know cold: why the words "fraud" and "reject" are banned from the product, and what
  "review item, not accusation" means for the system's design (this is a framing decision
  that shapes M4's rule pack — see Topic 8).

### Topic 2. Schemas as contracts
Why `schemas/` is the single source of truth every module imports from, and the
difference between the two schema families in this repo.
- Files: [schemas/common.py](schemas/common.py), [schemas/documents.py](schemas/documents.py),
  [schemas/ground_truth.py](schemas/ground_truth.py), [schemas/claim.py](schemas/claim.py),
  [schemas/findings.py](schemas/findings.py)
- Know cold: the distinction between `ground_truth` models (certain, used by datagen /
  eval) and `ExtractedField`-wrapped models (uncertain, produced by the pipeline) —
  explain why a *value* alone isn't enough and every extracted field needs
  `{value, confidence, source, evidence, flags}` wrapped around it.

### Topic 3. Synthetic data generation & MediClaim-Bench
How a claim is generated from nothing — seeded fake data → Jinja/HTML templates →
Chromium-rendered PDF — and why determinism (same seed → byte-identical output) is a
hard requirement, not a nice-to-have.
- Files: [datagen/cli.py](datagen/cli.py), [datagen/fake_data.py](datagen/fake_data.py),
  [datagen/render.py](datagen/render.py), [datagen/faults.py](datagen/faults.py),
  [datagen/sampler.py](datagen/sampler.py)
- Run it: `make datagen-sample` (or `./run.ps1 datagen-sample`), then open
  `data/sample/claim.pdf` and `data/sample/ground_truth.json` side by side.
- Know cold: what the **fault injector** does (the 7 fault types), and why faults need
  their own ground truth (this is what M4's audit engine is graded against — Topic 9).

---

## Track B — The extraction pipeline (M1 → M3.5)

### Topic 4. Ingest: turning a PDF into words + boxes
How MediProof reads a merged PDF's text layer (not OCR, for now) into word-level tokens
with bounding boxes, masks the synthetic watermark, and gates page quality.
- Files: [pipeline/m1_ingest/ingest.py](pipeline/m1_ingest/ingest.py),
  [pipeline/ir.py](pipeline/ir.py)
- Know cold: what the **per-page quality gate** protects against ("garbage in must not
  become confident garbage out" — plan.md §M1) and why this matters more once a real OCR
  path exists for scanned/phone-photo documents.

### Topic 5. Segmentation & classification
How a single merged PDF (20–40 pages, one long stream) gets split into ~9 typed
documents, and the staged-complexity design (P0 keyword baseline → P1 embeddings →
P2 LayoutLMv3, "only build the expensive thing if the cheap thing fails").
- Files: [pipeline/m2_segment/segment.py](pipeline/m2_segment/segment.py)
- Know cold: what "P0/P1/P2" means as an engineering philosophy — be ready to explain why
  this project didn't jump straight to a fine-tuned model, and what metric would trigger
  the upgrade (plan.md §M2).

### Topic 6. Hybrid extraction — the deterministic layer
Regex, checksums, table-math validation, date logic — the "cheap, high-confidence" layer
that resolves most fields without ever touching an LLM.
- Files: [pipeline/m3_extract/extract.py](pipeline/m3_extract/extract.py),
  [pipeline/m3_extract/confidence.py](pipeline/m3_extract/confidence.py)
- Know cold: the base confidence numbers a validated rule gets (0.95) vs. an unvalidated
  one (0.85), and why confidence is scaled by *source OCR word confidence* even for rule
  extractions — this is the number that later decides auto-accept vs. review.

### Topic 7. Hybrid extraction — the LLM fallback + confidence fusion
**This is the technical centerpiece — spend the most time here.** The LLM is called only
for fields the deterministic layer left weak or empty; self-consistency sampling (k=3)
turns model *agreement* into a confidence number; rule and LLM values are then fused.
- Files: [pipeline/m3_extract/fuse.py](pipeline/m3_extract/fuse.py),
  [pipeline/m3_extract/llm_client.py](pipeline/m3_extract/llm_client.py)
- Know cold, precisely (be ready to derive these, not just recite them):
  - Self-consistency: sample k=3 → 3/3 agree = 0.85 base, 2/3 = 0.60, 0/1 = 0.30;
    a passing validator adds +0.10, a failing one caps at 0.30 (`fuse.py:llm_confidence`).
  - Fusion when both a rule and an LLM value exist: **agree** → `max(conf)+0.05`;
    **conflict** → forced to 0.25 and auto-flagged `rule_llm_conflict` for human review
    (`fuse.py:fuse_field`) — explain *why* disagreement should lower confidence rather
    than average it.
  - The **LLM output contract**: a reply must parse into the field's Pydantic schema; on
    failure the client retries with error feedback (max 2 attempts), then degrades to
    `value=None, confidence=0` — the pipeline is designed to *never crash* on a bad LLM
    reply (`llm_client.py`).
  - **Record/replay**: why LLM calls are recorded to `tests/fixtures/llm/` and replayed in
    CI (deterministic, free, fast), with live calls gated behind `LLM_LIVE=1` and a hard
    `LLM_BUDGET_USD` cap.
- The "why this beats pure-LLM extraction" argument: hybrid routing means the LLM only
  touches the ~4% of fields rules can't resolve — this is the unit-economics story in
  the benchmarks table.

### Topic 8. Value grounding
How a value the LLM (or a rule) produced gets mapped back to *where it lives* on the
page — fuzzy string matching against OCR tokens to recover `{page, bbox}` evidence, which
is what makes click-to-highlight and audit-report evidence actually work.
- Files: [pipeline/m3_extract/grounding.py](pipeline/m3_extract/grounding.py)
- Know cold: what happens when grounding *fails to find a match* (confidence gets capped
  and the field flagged) — explain why an ungrounded high-confidence value is treated as
  more dangerous than a low-confidence one.

---

## Track C — Cross-document reasoning & serving

### Topic 9. The cross-document audit engine
The config-driven rule pack that reconciles documents against each other: identity
consistency, bill arithmetic, unmatched medications, missing lab reports, duplicate line
items — each producing a severity-scored, evidence-linked "review item."
- Files: [pipeline/m4_audit/audit.py](pipeline/m4_audit/audit.py),
  [schemas/findings.py](schemas/findings.py)
- Know cold: why the drug↔diagnosis check is restricted to a small **curated** mapping
  instead of general clinical inference (plan.md §M4) — this is a deliberate scope
  boundary, and a professor will probe exactly this kind of "why didn't you just let the
  LLM decide" question.

### Topic 10. Completeness checking
The required-documents checklist per claim type, and why "missing lab report" is treated
as a first-class audit finding rather than silently absent data.
- Files: [pipeline/m5_complete/complete.py](pipeline/m5_complete/complete.py)

### Topic 11. Orchestration, API, and the HITL dashboard
How M1–M5 are wired into one pipeline run, exposed over FastAPI, and consumed by the
React dashboard for the four core human-in-the-loop interactions (view, click-to-evidence,
correct, approve).
- Files: [pipeline/orchestrator.py](pipeline/orchestrator.py), [api/app.py](api/app.py),
  [api/service.py](api/service.py), [api/db.py](api/db.py), [ui/README.md](ui/README.md)
- Run it: `make demo` (or `./run.ps1 demo`), open the dashboard, click a finding, watch
  the bbox highlight — connect that UI moment back to Topic 8 (grounding) and Topic 9
  (audit findings) concretely.

### Topic 12. Evaluation methodology
How the benchmark numbers in the README are produced, and — more importantly — why the
evaluation is trustworthy: the unseen-template split that prevents "tuning on the test
set" without realizing it.
- Files: [evals/harness.py](evals/harness.py), [evals/cli.py](evals/cli.py),
  [evals/report.py](evals/report.py), [evals/RESULTS.md](evals/RESULTS.md)
- Run it: `make eval` and diff the regenerated README tables against what's committed.
- Know cold: the **anti-circularity split** — build/tune on some hospital letterheads,
  report numbers only on unseen ones (plan.md §7) — and be ready to explain why this
  matters more than the headline accuracy numbers themselves.

---

## Track D — The honest gaps (a professor will ask about these)

### Topic 13. What's *not* done yet, and why
The synthetic-to-real gap, the OCR path for scanned/phone-photo documents, and
calibration (ECE) — framed as scoped-out future work, not oversights.
- Read: [README.md](README.md) §"Build status" → "Honest scope" callout, plan.md §9
  (Week 8) and §10a (cut lines).
- Know cold: *why* the current 100% benchmark numbers are expected and not that
  impressive on their own — they're measured on digital-text-layer synthetic PDFs with a
  real text layer, not noisy scans. Be ready to state this limitation proactively rather
  than have it be found — that's the strongest signal of technical maturity you can give
  a professor.

---

## Suggested one-hour prep session before the pitch

If you only have an hour: do Topics 1, 2, 7, 9, and 13 — framing, contracts, the hybrid
extraction/confidence-fusion core (the most "AI" part), the audit engine, and the honest
limitations. That combination covers *what it does*, *the interesting technical idea*,
*why it's trustworthy*, and *what you'd do next* — which is what most professors actually
probe for.
