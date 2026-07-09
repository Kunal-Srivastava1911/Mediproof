# CLAUDE.md — MediProof agent conventions

Source of truth for scope is [plan.md](plan.md). This file is the operating manual for
any AI coding agent (or human) working in this repo.

## Golden rules

1. **Contracts-first.** `schemas/` is the single source of truth. Every module imports
   its types from `schemas/`. Do **not** modify a schema without an explicit,
   human-approved task. Changing a contract is a breaking change to every downstream module.
2. **One module per session.** Never cross module boundaries in a single task.
   Modules are: `datagen`, `m1_ingest`, `m2_segment`, `m3_extract`, `m4_audit`,
   `m5_complete`, `api`, `ui`, `evals`.
3. **Every module task = implement + pytest tests + update that module's README stub.**
   A task is done only when `make test-<module>` passes.
4. **Golden-file tests.** Each module has input fixtures → expected JSON outputs checked
   into `tests/golden/`. Regressions fail CI.
5. **No new dependency without a pinned version** added to `pyproject.toml`.
6. **Deterministic seeds everywhere** (datagen, sampling, model calls). Reproducibility is
   non-negotiable — a fixed seed must reproduce byte-identical ground truth.

## Language & framing (non-negotiable)

- MediProof is **documentation QA**, not adjudication and not clinical decision-making.
- Findings are **review items**, never accusations. The words **"fraud"** and **"reject"**
  do not appear anywhere in product code, UI, or reports. Use "requires review",
  "unmatched", "inconsistent".
- Public repo + MediClaim-Bench contain **synthetic data only**. Real samples stay local,
  de-identified, and are never committed.

## Layout

```
schemas/       Pydantic v2 models = contracts (human-owned)
datagen/       synthetic generator + fault injector
pipeline/
  m1_ingest/   m2_segment/  m3_extract/  m4_audit/  m5_complete/
api/           FastAPI app
ui/            React dashboard
evals/         eval harness (CLI) + golden files
tests/         pytest; golden-file tests per module
```

## LLM usage

- All LLM calls go through the thin client in `pipeline/m3_extract/llm_client.py`.
- **Record/replay:** responses are recorded to `tests/fixtures/llm/`. Tests and CI replay
  from fixtures — deterministic, free, fast. Live calls only when `LLM_LIVE=1`.
- **Budget cap:** `LLM_BUDGET_USD` hard-stops the client and logs when exceeded.
- **Output contract:** an LLM reply must parse into the target field's Pydantic schema;
  on failure retry with error feedback (max 2), then emit `value=null, confidence=0`.
  The pipeline never crashes on a malformed LLM reply.

## Commands

- `make datagen-sample` — render sample docs to PDF + ground-truth JSON.
- `make test` / `make test-<module>` — run the suite / one module's suite.
- `make eval` — regenerate the README benchmark tables.
- `make demo` — build compose + seed a sample claim + open the dashboard.

Windows without `make`: use `./run.ps1 <target>` (mirrors the Makefile).

## Task decomposition

Each plan module → 3–6 tasks of ≤ ~300 LOC, phrased as:
context (schema + fixture paths) → deliverable → acceptance test.
Backlog lives in [plan.md](plan.md) §9.
