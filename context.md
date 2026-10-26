# MediProof — Project Context (for resume / interview use)

> **How to use this file:** Paste it into Claude (or any LLM) with a prompt like
> *"Here's context on a project I built. Draft 3–4 resume bullets tailored to a
> [backend / ML / full-stack / applied-AI] role, quantified and honest."*
> Everything below is factual and grounded in the actual codebase. The **Honest scope**
> section matters — it keeps your bullets defensible when an interviewer probes.

---

## One-line pitch

**MediProof** is a claim-readiness / documentation-QA engine for Indian health-insurance
claims: it ingests a merged claim PDF (discharge summary, hospital bill, pharmacy bills, lab
reports, prescriptions), extracts every field with a confidence score, cross-checks the
documents against each other, and surfaces inconsistencies to a human reviewer — with every
value clickable back to its exact location on the page.

**Framing that sets it apart:** it's deliberately scoped as *documentation QA, not fraud
detection or claim adjudication*. The system flags "review items"; a human makes every
decision. (The words "fraud" and "reject" appear nowhere in the product — a conscious
product/ethics decision, not an accident.)

## The problem it solves

An Indian health-insurance claim is a 20–40 page stack from half a dozen sources. Claims get
rejected not because the treatment was wrong but because the *paperwork* is inconsistent —
bill totals don't add up, a drug is billed but never prescribed, a lab test is charged for but
its report is missing, dates conflict. MediProof is a **pre-submission audit**: catch those
documentation problems *before* the file is submitted.

## Architecture — a 7-stage pipeline

1. **M1 Ingest** — read words + bounding boxes from the PDF text layer; per-page readability
   quality gate; watermark masking. (OCR path for scans is a documented upgrade hook.)
2. **M2 Segment** — classify and split the page stream into ~9 typed documents.
3. **M3 Extract** — **hybrid extraction**: a deterministic layer (regex, checksums, table
   arithmetic, date logic) does most of the work; an LLM fallback handles unseen layouts /
   low-structure fields; a **confidence-fusion** step assigns each field a score in [0,1].
4. **M3.5 Ground** — map every extracted value back to its OCR word boxes → `{page, bbox}`
   evidence (fuzzy matching via rapidfuzz). This is what powers click-to-source in the UI.
5. **M4 Audit** — a config-driven rule pack runs cross-document consistency checks and emits
   severity-scored review items.
6. **M5 Completeness** — required-documents checklist per claim type.
7. **M6/M7 API + Dashboard + Outputs** — FastAPI serves the assembled claim graph; a React
   dashboard renders it; JSON claim graph + audit report are the outputs.

**The central idea:** confidence-driven human-in-the-loop. Each field's confidence bucket
decides whether a human ever looks at it — green (≥0.8) auto-accept, amber (0.5–0.8) review
queue, red (<0.5) mandatory review. The system knows what it doesn't know and routes
uncertainty to a person instead of silently guessing.

## Key technical highlights (the differentiators to emphasize)

- **Hybrid rule + LLM extraction with a cost argument.** The deterministic layer fills
  **96.2%** of fields; the LLM only touches low-confidence ones — measurably cheap, not just
  "we called an LLM."
- **Grounding / auditability.** Every value and every finding stores a normalized bounding
  box (resolution-independent 0–1 coords), so a reviewer verifies at a glance rather than
  trusting a black box.
- **Contracts-first architecture.** Pydantic v2 schemas are the single source of truth; every
  module imports its types from there. Modules are independently testable against golden files.
- **Deterministic, testable non-determinism.** All LLM calls go through one thin client that
  records responses to fixtures; tests/CI replay from fixtures — deterministic, free, fast
  (live calls only behind a flag, under a hard USD budget cap). The pipeline **never crashes
  on a malformed LLM reply**: it retries with error feedback (max 2), then emits
  `value=null, confidence=0`.
- **Reproducibility as a hard rule.** A fixed seed reproduces byte-identical synthetic ground
  truth; golden-file tests catch regressions in CI.
- **Two-audience product surface.** A submitter site (upload a claim, track status: not
  reviewed / denied / approved) and a reviewer dashboard (confidence-colored fields,
  click-to-evidence, inline correction logged as training data, persisted approve/deny).

## Tech stack

- **Backend:** Python 3.11, FastAPI, Pydantic v2, SQLModel + SQLite (schema written
  Postgres-compatible), pypdfium2 (PDF rasterization), rapidfuzz (grounding).
- **Frontend:** React 18, TypeScript, Vite, Tailwind CSS.
- **Data/ML:** seeded synthetic data generator (Jinja → headless-Chromium/Playwright PDF
  rendering), a thin LLM client with record/replay fixtures + budget cap + schema-validated
  outputs.
- **Tooling & infra:** pytest + vitest (golden-file test suites), ruff, Docker + docker-compose
  (API + dashboard), a Render deploy blueprint, deterministic seeds throughout.

## Quantified results

*(Produced by an automated eval harness — `make eval` — on synthetic, digital claim PDFs.
Read the Honest-scope note before quoting these.)*

- **Document classification:** 100% (149/149 documents), P0 keyword baseline.
- **Field extraction:** 100% exact-match vs ground truth across 5 document types.
- **Audit engine:** 100% recall across all **7 fault types** (inflated line item, date
  mismatch, drug/diagnosis mismatch, missing lab report, duplicate billing, name mismatch,
  bill arithmetic error), with **0 false positives** on clean claims (0 severe review items
  across 16 clean files).
- **Hybrid economics:** deterministic layer fills **96.2%** of fields; **0 LLM calls** needed
  on the clean digital set.
- **Latency:** ~**265 ms/claim** median (digital path, no OCR).

## Scale & rigor

- ~**3,700 lines of Python** across `schemas/`, `datagen/`, `pipeline/` (M1–M5), `api/`,
  `evals/`, plus ~**800 lines of TypeScript/React** for the dashboard.
- **90+ automated tests** (pytest golden-file suites per module + vitest for the UI).
- Built module-by-module against a fixed plan; contracts-first, seed-reproducible, Dockerized.
- Data ethics baked in: **synthetic data only** in the repo; every page watermarked
  `SPECIMEN — SYNTHETIC DATA`; a DPDP-aware posture (real samples stay local + de-identified);
  a CI PII scan (Aadhaar/PAN/phone patterns) guards pushes.

## Honest scope (read before quoting metrics — this keeps you credible)

- The 100% numbers are on **synthetic, digital** PDFs with a real text layer (no OCR noise),
  so extraction is near-perfect *by construction*. Don't lead a resume bullet with
  "100% accuracy" — it invites a deflating follow-up. Lead with the **engineering**: the
  hybrid cost model (96% deterministic fill), confidence-based HITL routing, 0 false positives,
  grounded evidence, sub-300ms latency.
- The **OCR path** for scanned/phone-photo documents (OpenCV + PaddleOCR) is the next block of
  work — the honest synthetic-to-real gap is acknowledged, not hidden.
- The LLM fallback is fully wired (record/replay) but rarely fires on clean digital claims —
  which is the point of the hybrid design, not a gap.
- This is a solo, AI-assisted build. Own the **design decisions and the "why"** — that's what
  an interviewer actually tests. Pick the 2–3 areas you understand best (confidence-based HITL,
  hybrid extraction economics, grounding/auditability, testing non-determinism) and steer there.

## Sample resume bullets (starting points — tailor + trim)

- Built **MediProof**, a documentation-QA pipeline for health-insurance claims (Python /
  FastAPI / React) that ingests multi-document claim PDFs, extracts fields with per-field
  confidence, and cross-checks documents to surface inconsistencies for human review.
- Designed a **hybrid rule + LLM extraction** engine where a deterministic layer fills ~96% of
  fields and confidence scoring routes only low-confidence values to human review — cutting LLM
  usage to near-zero on structured inputs while keeping every output auditable.
- Grounded every extracted value to a page bounding box, powering **click-to-evidence** review
  in a React/TypeScript dashboard; achieved 0 false positives on clean claims across a seeded
  synthetic benchmark with an automated eval harness.
- Engineered for reproducibility and testability: **contracts-first** Pydantic schemas,
  deterministic seeds, LLM **record/replay** fixtures, and **90+ golden-file tests**; packaged
  with Docker and a one-command deploy blueprint.

---

*Repo: github.com/Kunal-Srivastava1911/Mediproof · Apache-2.0 · synthetic data only.*
