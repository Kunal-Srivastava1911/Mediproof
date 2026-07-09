# api/ — M6 FastAPI app (W7)

- `POST /claims` — upload a claim file; processed async via FastAPI BackgroundTasks
  (Celery/Redis is a documented upgrade path, not MVP).
- `GET /claims/{id}` — the `ClaimFile` graph (fields, findings, completeness).
- `POST /claims/{id}/review` — approve/correct; corrections stored as training data.

Storage: SQLite via SQLModel (schema written Postgres-compatible — swap is a connection
string). Tables: claims, fields, findings, corrections.

**DoD:** stranger-test — someone else runs `make demo` from the README only and sees a
seeded claim with findings in the dashboard in < 5 minutes.
