"""M6 — FastAPI application (plan §M6).

Endpoints:
  POST /claims                 upload a claim PDF; processed async via BackgroundTasks
  GET  /claims                 list claim summaries
  GET  /claims/{id}            the full claim graph (ClaimFile)
  POST /claims/{id}/review     apply a reviewer correction (logged as training data)
  GET  /healthz                liveness

Async is FastAPI BackgroundTasks (Celery/Redis is a documented upgrade path, not MVP).
Storage is SQLite via SQLModel, schema written Postgres-compatible.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlmodel import Session, select

from api.db import ClaimRow, CorrectionRow, init_db, make_engine
from api.service import apply_correction
from pipeline import run_pipeline
from pipeline.orchestrator import DEFAULT_CLAIM_TYPE
from schemas.claim import ClaimFile, ClaimStatus, Correction


class ReviewIn(BaseModel):
    document_id: str
    field_path: str
    new_value: str
    reviewer: str | None = None


def create_app(database_url: str | None = None, storage_dir: str | None = None) -> FastAPI:
    engine = make_engine(database_url or os.getenv("DATABASE_URL", "sqlite:///./data/mediproof.db"))
    init_db(engine)
    storage = Path(storage_dir or os.getenv("MEDIPROOF_STORAGE", "./data/uploads"))
    storage.mkdir(parents=True, exist_ok=True)

    app = FastAPI(title="MediProof API", version="0.1.0",
                  description="Claim-readiness audit engine — documentation QA, not adjudication.")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                       allow_headers=["*"])

    def _process(claim_id: str, pdf_path: str, claim_type: str) -> None:
        try:
            claim = run_pipeline(pdf_path, claim_id=claim_id, claim_type=claim_type)
            graph, status = claim.model_dump_json(), claim.status.value
        except Exception as exc:  # never leave a claim stuck; record the failure
            graph, status = json.dumps({"claim_id": claim_id, "error": str(exc)}), \
                ClaimStatus.failed.value
        with Session(engine) as session:
            row = session.get(ClaimRow, claim_id)
            if row:
                row.graph, row.status = graph, status
                session.add(row)
                session.commit()

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.post("/claims", status_code=202)
    async def create_claim(
        background: BackgroundTasks,
        file: UploadFile,
        claim_id: str | None = None,
        claim_type: str = DEFAULT_CLAIM_TYPE,
    ) -> dict:
        cid = claim_id or f"CLAIM-{uuid4().hex[:10]}"
        dest = storage / f"{cid}.pdf"
        dest.write_bytes(await file.read())
        with Session(engine) as session:
            session.merge(ClaimRow(id=cid, status=ClaimStatus.processing.value,
                                   claim_type=claim_type, graph="{}"))
            session.commit()
        background.add_task(_process, cid, str(dest), claim_type)
        return {"claim_id": cid, "status": ClaimStatus.processing.value}

    @app.get("/claims")
    def list_claims() -> list[dict]:
        out = []
        with Session(engine) as session:
            for r in session.exec(select(ClaimRow)).all():
                graph = json.loads(r.graph) if r.graph and r.graph != "{}" else {}
                out.append({
                    "claim_id": r.id, "status": r.status, "claim_type": r.claim_type,
                    "created_at": r.created_at.isoformat(),
                    "n_findings": len(graph.get("findings", [])),
                    "n_documents": len(graph.get("documents", [])),
                })
        return out

    @app.get("/claims/{claim_id}")
    def get_claim(claim_id: str) -> dict:
        with Session(engine) as session:
            row = session.get(ClaimRow, claim_id)
            if row is None:
                raise HTTPException(404, f"claim {claim_id} not found")
            graph = row.graph
        return json.loads(graph) if graph else {}

    @app.post("/claims/{claim_id}/review")
    def review_claim(claim_id: str, review: ReviewIn) -> dict:
        with Session(engine) as session:
            row = session.get(ClaimRow, claim_id)
            if row is None or not row.graph or row.graph == "{}":
                raise HTTPException(404, f"claim {claim_id} not processed")
            claim = ClaimFile.model_validate_json(row.graph)
            try:
                logged = apply_correction(claim, Correction(**review.model_dump()))
            except KeyError as exc:
                raise HTTPException(422, str(exc)) from exc
            updated = claim.model_dump_json()
            row.graph = updated
            session.add(row)
            session.add(CorrectionRow(claim_id=claim_id, **logged.model_dump(
                include={"document_id", "field_path", "old_value", "new_value", "reviewer"})))
            session.commit()
        return json.loads(updated)

    return app


app = create_app()
