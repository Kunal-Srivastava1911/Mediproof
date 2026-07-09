# MediProof — plan.md
**A claim-readiness audit engine for Indian health-insurance claim files.**
Built solo, AI-assisted (Claude Code), 8 weeks part-time. Target: portfolio project demonstrating document-AI architecture (segmentation → hybrid extraction → cross-document audit → HITL) on healthcare documents.

---

## 1. Product overview

Input: one merged PDF / set of images = a health claim file (discharge summary, itemized hospital bill, pharmacy bills, lab reports, prescriptions, claim form, ID docs).
Output:
1. Structured JSON of every extracted field
2. A severity-scored **audit report** (inconsistencies, arithmetic errors, missing documents, tampering signals)
3. A reviewer dashboard (HITL) with confidence-colored fields and click-to-source highlighting

Positioning: patient/hospital-side "pre-submission audit" — catch the documentation problems that cause claim rejections *before* filing.

## 2. Goals / Non-goals

**Goals**
- End-to-end working pipeline on synthetic + small real sample set
- Published benchmark dataset (MediClaim-Bench) + eval harness
- Hybrid extraction (deterministic rules + LLM fallback) with per-field confidence
- Cross-document audit engine with severity-scored findings
- Deployable demo (Docker) + HITL review UI

**Non-goals**
- Clinical decision-making of any kind
- Insurer-side adjudication or payment decisions
- Production-scale throughput

## 3. System architecture

```
Upload (PDF / phone photos)
        │
        ▼
[M1  Ingest & Preprocess]        deskew, denoise, orientation, DPI-normalize,
        │                        digital-vs-scan detection, OCR (words + boxes)
        ▼
[M2  Page-Stream Segmenter       split merged PDF into typed documents
     + Classifier]               (~9 classes)
        │
        ▼
[M3  Hybrid Extraction]          per doc type:
   ├─ deterministic layer          regex, checksums, table-math validation,
   │                               date logic, code-format validation
   ├─ LLM/VLM fallback             unseen layouts, low-structure fields
   └─ confidence fusion            per-field confidence score
        │
        ▼
[M3.5 Value Grounding]           map every extracted value back to OCR
        │                        word boxes (page + bbox evidence)
        ▼
[M4  Cross-Document Audit]       consistency rules across documents,
        │                        severity-scored findings
        ▼
[M5  Completeness Checker]       required-docs checklist per claim type
        │
        ▼
[M6  API + HITL Dashboard]       FastAPI + React; approve/correct;
        │                        corrections logged
        ▼
[M7  Outputs]                    JSON API response + PDF audit report
```

## 4. Module specs

### M1 — Ingest & Preprocess
- Accept PDF, JPG, PNG. Split PDF to page images (300 DPI).
- OpenCV pipeline: deskew (Hough), denoise, contrast normalize, orientation fix.
- Detect digital PDF (extract text layer directly) vs scanned (OCR path).
- OCR: PaddleOCR → words + bounding boxes + per-word confidence.
- **Quality gate:** per-page readability score (Laplacian blur variance + contrast + OCR mean confidence). Below threshold → page marked `unreadable`, excluded from auto-accept, surfaced in dashboard as "re-upload requested". Garbage in must not become confident garbage out.

### M2 — Segmentation + Classification
- Page classifier over 9 classes: discharge_summary, hospital_bill, pharmacy_bill, lab_report, prescription, claim_form, id_document, pre_auth, other.
- **Staged approach (build cheapest first, upgrade only if metrics demand):**
  - **P0:** keyword/heuristic baseline on OCR text (doc titles, letterhead cues) — 1 day, gives a floor.
  - **P1:** text-embedding classifier (sentence-transformers on OCR text of page) — cheap, no GPU.
  - **P2 (only if P1 < 92% accuracy):** LayoutLMv3-base + LoRA on synthetic pages (Colab GPU).
- Boundary detection: class-change + "first page" cues (letterheads, doc titles) to split the page stream into documents.

### M3 — Hybrid Extraction
Per-document-type field schemas (Pydantic). Two layers:
- **Deterministic:** regex + validators — bill line items must sum to totals; admission_date < discharge_date; pharmacy purchase dates within admission window; ICD-10 code format; lab values parsed with units + reference ranges.
- **LLM fallback:** Gemini Flash (or Claude Haiku) with page image + OCR text for fields the deterministic layer can't fill or fills with low confidence.
- **Confidence fusion (concrete):** every field gets `confidence ∈ [0,1]`:
  - Rule-extracted + validator passes (checksum/arithmetic/date-logic) → 0.95 base, scaled by mean OCR word confidence of source tokens.
  - LLM-extracted → self-consistency: sample k=3, agreement 3/3 → 0.85, 2/3 → 0.6, else 0.3; validator pass adds +0.1, fail forces ≤ 0.3.
  - Rule and LLM both produce a value: match → max(conf)+0.05; conflict → 0.25 and auto-flag for HITL.
  - Thresholds: ≥0.8 green (auto-accept), 0.5–0.8 amber (review queue), <0.5 red (mandatory review). Calibrated on a held-out validation split (temperature scaling) in W8.
- **LLM output contract:** responses must parse into the field's Pydantic schema; on parse/validation failure retry with error feedback (max 2), then emit `value=null, confidence=0` — the pipeline never crashes on a malformed LLM reply.

### M3.5 — Value Grounding
LLMs return values, not coordinates. For every extracted field, fuzzy-match the value string against OCR tokens on the source page (normalized Levenshtein over token n-grams) to recover `{page, bbox}` evidence. No grounding found → confidence capped at 0.5 and field flagged. This is what makes click-to-highlight, tampering evidence, and the audit report's "evidence refs" actually work.

### M4 — Cross-Document Audit Engine
Rule pack (config-driven YAML), each rule → finding {id, severity: info|warning|critical, evidence refs}.
**Framing rule (non-negotiable):** findings are *documentation review items*, never accusations. UI/report language is "requires review / unmatched / inconsistent" — the words "fraud" and "reject" do not appear anywhere in the product. Every finding links its bbox evidence so a human can judge.
- Patient name / age / gender consistent across all docs (fuzzy match)
- **Unmatched-medication check (curated):** billed medications not found on any prescription, and prescription↔pharmacy-bill line matching. Drug↔diagnosis plausibility only via a small curated high-confidence mapping (e.g., cardiac stent line item on a claim whose only ICD code is a hernia) — anything outside the curated set is *not* flagged. No general clinical inference.
- Every lab test billed has a corresponding lab report present
- Bill arithmetic re-validation at claim level; duplicate line items
- Non-payable consumables flagging (standard list)
- Tampering signals: PDF metadata anomalies, font inconsistency in amount regions, copy-move detection on stamps

### M5 — Completeness Checker
Claim-type → required document checklist; output missing/present matrix.

### M6 — API + HITL Dashboard
- FastAPI: POST /claims (async via FastAPI BackgroundTasks — Celery/Redis is a documented upgrade path, not MVP), GET /claims/{id}, POST /claims/{id}/review.
- SQLite via SQLModel for claims, fields, findings, corrections (schema written Postgres-compatible; swap is a connection string).
- React dashboard: doc image beside extracted fields, confidence colors (green/amber/red), click field → highlight bounding box, approve/correct; corrections stored as training data.

### M7 — Outputs
JSON (full claim graph) + generated PDF audit report (findings by severity).

## 5. Data strategy — MediClaim-Bench

- **Synthetic generator:** HTML/Jinja templates → PDF for each doc type. 6–8 hospital letterhead styles, 3–4 lab layouts, thermal-receipt style pharmacy bills.
- **Brand & legal safety:** all institutions fictional (no real hospital/insurer/lab names or logos); every generated page carries a faint "SPECIMEN — SYNTHETIC DATA" watermark. Watermark region is masked out of OCR evaluation so it doesn't pollute metrics.
- **Content realism:** ICD-10 code list (WHO), Indian drug names from open Jan Aushadhi/CDSCO lists, realistic charge structures (room rent, OT, consumables, pharmacy).
- **Degradation:** Augraphy — scanner noise, skew, stains, low-DPI, phone-photo warp, thermal fade profile.
- **Fault injection:** ~10% of files get seeded problems (inflated line item, date mismatch, drug not matching diagnosis, missing lab report, duplicate billing) with ground-truth labels → this is what the audit engine is evaluated against.
- Target: ~300 synthetic claim files (~3,000 pages) + small real, redacted sample set (local only).
- Template metadata is stored per file so the eval harness can enforce the unseen-template split automatically (§7).

## 6. Tech stack

Python 3.11, FastAPI (+BackgroundTasks), SQLite/SQLModel (Postgres-ready), PaddleOCR, OpenCV, sentence-transformers (P1 classifier), LayoutLMv3 LoRA only if P2 triggered, Gemini Flash API, Pydantic v2, React + Vite + Tailwind, Docker Compose (single compose file), GitHub Actions.

## 7. Evaluation plan

**Anti-circularity split (by template, not by file):** build/tune on 5 hospital letterheads + 2 lab layouts; evaluate on 3 unseen letterheads + 1 unseen lab layout + the local real redacted set. Splits are seed-fixed and committed. Reported numbers come from unseen templates only.

**Metrics (all produced by `make eval` — a CLI harness that regenerates README tables):**
- Classification: accuracy + confusion matrix; segmentation: boundary F1.
- Field extraction: exact-match and normalized-match (dates/amounts/units canonicalized) P/R/F1 per doc type; ANLS for free-text fields.
- Audit engine: precision/recall per fault type vs injected ground truth; false-positive rate on clean files (the number a buyer cares about most).
- **Coverage–accuracy curve (headline chart):** accuracy of auto-accepted fields as a function of % of fields sent to human review, ordered by confidence — the "review the bottom X% to reach Y% accuracy" story. Plus calibration curve (ECE) after temperature scaling.
- **Cost & latency:** per-page token accounting logged on every LLM call; table comparing hybrid vs pure-LLM (cost/page, median latency, accuracy). This is the unit-economics argument.

## 8. Vibecoding build system (Claude Code)

The plan is written to be executed by AI coding agents. Rules that make that work:

**Repo layout (monorepo)**
```
mediproof/
  CLAUDE.md                 # agent conventions (below)
  plan.md                   # this file — source of truth for scope
  schemas/                  # Pydantic models = contracts (human-owned)
  datagen/                  # synthetic generator + fault injector
  pipeline/
    m1_ingest/  m2_segment/  m3_extract/  m4_audit/  m5_complete/
  api/                      # FastAPI app
  ui/                       # React dashboard
  evals/                    # eval harness (CLI) + golden files
  tests/                    # pytest; golden-file tests per module
```

**CLAUDE.md conventions (agent must follow)**
- Contracts-first: `schemas/` is the single source of truth. Agents may not modify schemas without an explicit human-approved task; all modules import from it.
- One module per session; never cross module boundaries in a single task.
- Every module task = implement + pytest tests + update that module's README stub. Task is done only when `make test-<module>` passes.
- Golden-file tests: each module has input fixtures → expected JSON outputs checked into `tests/golden/`. Regressions fail CI.
- No new dependencies without adding to `pyproject.toml` with pinned versions.
- Deterministic seeds everywhere (datagen, sampling) for reproducibility.

**Task decomposition pattern:** each plan module → 3–6 Claude Code tasks of ≤ ~300 LOC each, phrased as: context (schema + fixture paths) → deliverable → acceptance test. Backlog kept in `plan.md` §9 so agent and human share one scope document.

**Runnability & guardrails**
- `make demo` = one command: builds compose, seeds one pre-processed sample claim file, opens the dashboard with findings already visible. A stranger goes from clone → wow in < 5 minutes.
- **LLM record/replay:** all LLM calls go through a thin client that records responses to fixtures; tests and CI replay from fixtures — deterministic, free, fast. Live calls only behind `LLM_LIVE=1`.
- **Budget cap:** `LLM_BUDGET_USD` env var; client hard-stops and logs when exceeded. Per-call token/cost logging feeds §7's cost table for free.
- **Secrets hygiene:** `.env.example` committed, `.env` gitignored; CI runs a secrets scanner + the PII pattern scan (§11) on every push. Non-negotiable in an AI-generated codebase.

## 9. Timeline (8 weeks, part-time) — with phase gates

Each week ends with a gate: a runnable artifact + passing golden tests. If a gate slips 3+ days, invoke the cut lines (§10a).

- **W1:** repo scaffold + CLAUDE.md + schemas v1; synthetic templates (bill, discharge, pharmacy). *DoD: `make datagen-sample` renders 3 doc types to PDF with ground-truth JSON.*
- **W2:** remaining templates, Augraphy degradation, fault injection, dataset v1. *DoD: 300 files generated with template metadata + fault labels; PII scan passes.*
- **W3:** M1 preprocess + OCR + quality gate; M2 classifier (P0→P1). *DoD: golden tests green; classifier ≥ 90% on unseen-template dev split, else schedule P2.*
- **W4:** M3 deterministic extraction + validators. *DoD: rule-layer F1 reported per doc type via `make eval`.*
- **W5:** M3 LLM fallback (record/replay client) + confidence fusion + M3.5 grounding. *DoD: end-to-end JSON for a full claim file; every field carries confidence + bbox or a flag.*
- **W6:** M4 audit engine + M5 completeness. *DoD: findings precision/recall vs injected faults reported; FP rate on clean files reported. This is the MVP floor.*
- **W7:** M6 API + dashboard (4 core interactions); Dockerize; `make demo`. *DoD: stranger-test — someone else runs the demo from README only.*
- **W8:** full benchmark on unseen templates + real set, calibration, cost table; README hero, demo video, blog post; outreach. *DoD: email sent.*

## 10. Risks → mitigations

- OCR quality on degraded receipts → quality gate (M1) routes unreadables to re-upload instead of poisoning metrics; thermal-fade augmentation makes the model see it in training.
- LLM cost creep → hard budget cap (§8 guardrails) + hybrid routing means LLM only touches low-confidence fields.
- Scope creep on dashboard polish → cut lines below; dashboard core = 4 interactions only (view, click-to-evidence, correct, approve).
- Synthetic-to-real gap → unseen-template eval + local real redacted set as honesty check; gap reported openly in README (credibility > inflated numbers).

## 10a. Cut lines (ordered — drop from the top when a gate slips 3+ days)

1. Handwritten prescription extraction (already a stretch goal)
2. Copy-move/stamp forgery detection (mark "experimental" or drop; metadata + font-inconsistency signals stay)
3. PDF audit report (JSON + dashboard suffice for demo)
4. P2 classifier fine-tune (ship P1 embeddings if ≥ 90%)
5. Dashboard polish beyond the 4 core interactions

**Floor (never cut):** M1→M3.5 pipeline + 3 audit rules (name consistency, bill arithmetic, prescription↔pharmacy matching) + eval harness + `make demo`. That alone is a hirable artifact by end of W6.

## 11. Safety, privacy & data ethics

- **Scope disclaimer (README + report footer):** MediProof is documentation QA. It does not make clinical judgments, adjudicate claims, or determine payment. Outputs are inputs to human review.
- **DPDP posture:** health data is sensitive personal data. The public repo and MediClaim-Bench contain **synthetic data only** — enforced by a CI check that scans for Aadhaar/PAN/phone patterns before publish. Any real sample used for the synthetic-to-real gap check stays local, is de-identified first (patient identifiers masked via the same grounding bboxes), and is never committed.
- **De-identification module:** mask name/ID/phone regions on request — doubles as the demo of privacy-aware design.
- **Source licensing:** ICD-10 (WHO, with attribution), drug names from open government lists (Jan Aushadhi/NLEM), non-payable consumables from the standard IRDAI-aligned list — all cited in README.

## 12. Delivery & outreach

**README (the first 10 seconds):** hero GIF of the dashboard finding an inflated line item → benchmark tables (auto-generated by `make eval`) → coverage–accuracy curve → architecture diagram → quickstart. No wall of text before the numbers.
**Demo video (90s script):** upload a crumpled 40-page claim file → pipeline runs → findings appear by severity → click a finding → source bbox highlights → correct one field → export audit PDF.
**Blog post:** "Why hybrid beats pure-LLM for document extraction" using MediProof's own cost/accuracy table.
**Outreach (only after real numbers exist):** cold email to Vaultedge CEO + engineering leads — one line of story (built from watching a family claim fight), the coverage–accuracy chart inline, repo + video links, offer to demo in person (Bengaluru). Parallel: apply on careers page, post the blog on LinkedIn tagging document-AI topics.

---

## Changelog
- v1: initial plan.
- v2 (Council R1 — Staff Eng, ML Eng, Vibecoding Lead): staged P0→P2 classifier path instead of upfront fine-tuning; concrete confidence-fusion scheme with thresholds; full AI-agent build system (repo layout, CLAUDE.md conventions, contracts-first, golden-file tests, task decomposition); phase gates added to timeline.
- v3 (Council R2 — Backend Architect, Doc-AI Specialist, Frontend): infra simplified to SQLite + BackgroundTasks with documented upgrade path; M3.5 Value Grounding added (LLM values → bbox evidence) fixing click-to-highlight; per-page quality gate added to M1; LLM output contract with validated retry.
- v4 (Council R3 — Clinical-Informatics, DPDP/Privacy, Legal): audit reframed as review-items with no fraud/reject language; drug-diagnosis check restricted to curated high-confidence mapping; SPECIMEN watermarks + fictional brands in datagen; new §11 safety/privacy/ethics with CI PII scan, de-identification module, and source licensing.
- v5 (Council R4 — Eval Scientist, Cost Analyst, Hiring Manager): unseen-template holdout split to kill evaluation circularity; metrics fully specified (exact/normalized match, ANLS, FP rate on clean files, coverage–accuracy + calibration curves); per-call cost/latency accounting; README/demo-video/outreach concretely specified.
- v6 — FINAL (Council R5 — PM, DevOps, Red Team): §10a ordered cut lines + never-cut MVP floor; risks converted to risk→mitigation; `make demo` 5-minute runnability; LLM record/replay fixtures for deterministic free tests; budget cap + secrets/PII scanning in CI; per-week definition-of-done added to every gate.
