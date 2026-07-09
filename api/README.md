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
| `GET /healthz` | Liveness. |

Async is BackgroundTasks (Celery/Redis is a documented upgrade path, not MVP). Storage is
**SQLite via SQLModel**, schema written Postgres-compatible — the swap is a connection string
(`DATABASE_URL`). Tables: `claims` (the graph JSON), `corrections` (the training-data log).

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
