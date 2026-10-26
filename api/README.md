# api/ — FastAPI application (plan §M6)

The HTTP surface over the pipeline. `run_pipeline` (in `pipeline/orchestrator.py`) does the
work; this module persists claims and serves the review UI.

## Endpoints

| Method & path | Purpose |
|---------------|---------|
| `POST /claims` | Upload a claim PDF; processed **async** via FastAPI BackgroundTasks. Returns `{claim_id, status: processing}`. |
| `GET /claims` | Claim summaries (status, #findings, #documents). |
| `GET /claims/{id}` | The full `ClaimFile` graph — pages, typed documents with confidence-scored fields, findings, completeness. |
| `POST /claims/{id}/review` | Apply a reviewer correction; the field is marked human-verified (confidence 1.0) and the edit logged as training data. |
| `POST /claims/{id}/approve` · `/deny` | Record the reviewer's decision on the whole claim. |
| `POST /claims/{id}/findings/{fid}/decision` | Confirm / dismiss (with a reason) / promote a held-back item; logged to `finding_decisions` as verifier training data. Dismissed items leave the patient's checklist. |
| `GET /claims/{id}/checklist?lang=en\|hi` | The patient's fix-it checklist: verified, patient-facing, not-dismissed items, each with plain-language title + action (fixed English/Hindi templates), its detail (Claude-translated for Hindi, English if offline) and its sources (document, page, quote, bbox). |
| `POST /claims/{id}/ask` | Claim chat. Claude answers only from this file and must cite quotes; quotes not found in their document are dropped, and an answer left with no verifiable source is replaced by "I won't guess". `503` when Claude isn't configured. |
| `GET /healthz` | Liveness. |

The `ClaimFile` graph also carries the claim's `timeline`, `evidence_map` and `audit`
metadata (agents run, Claude calls/cost, verifier threshold, or why the agents were skipped).

Async is BackgroundTasks (Celery/Redis is a documented upgrade path, not MVP). Storage is
**SQLite via SQLModel**, schema written Postgres-compatible — the swap is a connection string
(`DATABASE_URL`). Tables: `claims` (the graph JSON), `corrections` and `finding_decisions`
(the training-data logs). One `LLMClient` per process, so `LLM_BUDGET_USD` caps the server.

## Run it

```bash
uvicorn api.app:app --reload        # or: ./run.ps1 api
# POST a generated claim:
curl -F "file=@data/sample/claim.pdf" "http://localhost:8000/claims?claim_id=demo"
curl http://localhost:8000/claims/demo | jq .findings
```

`create_app(database_url, storage_dir)` is a factory so tests get an isolated DB + upload dir.

Run `make test` (the `tests/api/` suite). **DoD:** stranger-test — someone runs `make demo`
from the README and sees a seeded claim with findings in the dashboard in < 5 minutes.
