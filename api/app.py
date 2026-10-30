"""M6 — FastAPI application (plan §M6).

Endpoints:
  POST /claims                 upload a claim PDF; processed async via BackgroundTasks
  GET  /claims                 list claim summaries
  GET  /claims/{id}            the full claim graph (ClaimFile)
  GET  /claims/{id}/status     the claim's status (read from the row; works mid-processing)
  POST /claims/{id}/review     apply a reviewer correction (logged as training data)
  POST /claims/{id}/approve    mark the claim reviewed — approved
  POST /claims/{id}/deny       mark the claim reviewed — denied
  POST /claims/{id}/findings/{fid}/decision   confirm / dismiss / promote one review item
  GET  /claims/{id}/checklist?lang=en|hi      the patient's fix-it checklist
  POST /claims/{id}/ask        claim chat: answers only from the file, with verified quotes
  GET  /healthz                liveness

Async is FastAPI BackgroundTasks (Celery/Redis is a documented upgrade path, not MVP).
Storage is SQLite via SQLModel, schema written Postgres-compatible.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from api.db import ClaimRow, CorrectionRow, FindingDecisionRow, init_db, make_engine
from api.patient import ask, checklist
from api.service import apply_correction
from pipeline import run_pipeline
from pipeline.m3_extract.llm_client import BudgetExceeded, LLMClient, LLMError, MissingFixture
from pipeline.m4_audit import build_evidence_map, build_timeline
from pipeline.orchestrator import DEFAULT_CLAIM_TYPE
from schemas.claim import ClaimFile, ClaimStatus, Correction
from schemas.findings import FindingDecision, FindingOrigin


class ReviewIn(BaseModel):
    document_id: str
    field_path: str
    new_value: str
    reviewer: str | None = None


class DecisionIn(BaseModel):
    reviewer: str | None = None


class FindingDecisionIn(BaseModel):
    decision: FindingDecision = FindingDecision.confirmed
    reason: str | None = None
    promote: bool = Field(default=False, description="show a held-back agent item")
    reviewer: str | None = None


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)


def create_app(
    database_url: str | None = None,
    storage_dir: str | None = None,
    llm_client: LLMClient | None = None,
) -> FastAPI:
    engine = make_engine(database_url or os.getenv("DATABASE_URL", "sqlite:///./data/mediproof.db"))
    init_db(engine)
    storage = Path(storage_dir or os.getenv("MEDIPROOF_STORAGE", "./data/uploads"))
    storage.mkdir(parents=True, exist_ok=True)
    llm = llm_client or LLMClient()  # one client per app: LLM_BUDGET_USD caps the process

    app = FastAPI(title="MediProof API", version="0.1.0",
                  description="Claim-readiness audit engine — documentation QA, not adjudication.")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                       allow_headers=["*"])

    def _process(claim_id: str, pdf_path: str, claim_type: str) -> None:
        try:
            claim = run_pipeline(pdf_path, claim_id=claim_id, claim_type=claim_type,
                                 llm_client=llm)
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
        data = await file.read()
        # The id is part of every AI prompt, so it is derived from the file itself: the same
        # PDF always gets the same id, and its recorded AI replies replay without a key.
        cid = claim_id or f"CLAIM-{hashlib.sha256(data).hexdigest()[:10]}"
        dest = storage / f"{cid}.pdf"
        dest.write_bytes(data)
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

    @app.get("/claims/{claim_id}/status")
    def get_status(claim_id: str) -> dict:
        """The claim's status from the row (reliable even while `graph` is still '{}')."""
        with Session(engine) as session:
            row = session.get(ClaimRow, claim_id)
            if row is None:
                raise HTTPException(404, f"claim {claim_id} not found")
            return {"claim_id": row.id, "status": row.status}

    @app.get("/claims/{claim_id}/pages/{page}.png")
    def page_image(claim_id: str, page: int) -> Response:
        """Rasterize one page of the uploaded claim PDF (for the dashboard's bbox overlay)."""
        import pypdfium2 as pdfium

        pdf_path = storage / f"{claim_id}.pdf"
        if not pdf_path.exists():
            raise HTTPException(404, f"claim {claim_id} pdf not found")
        doc = pdfium.PdfDocument(str(pdf_path))
        try:
            if page < 0 or page >= len(doc):
                raise HTTPException(404, f"page {page} out of range")
            image = doc[page].render(scale=2.0).to_pil()
        finally:
            doc.close()
        import io
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return Response(content=buf.getvalue(), media_type="image/png")

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

    def _decide(claim_id: str, decision: ClaimStatus) -> dict:
        with Session(engine) as session:
            row = session.get(ClaimRow, claim_id)
            if row is None or not row.graph or row.graph == "{}":
                raise HTTPException(404, f"claim {claim_id} not processed")
            if row.status == ClaimStatus.failed.value:
                raise HTTPException(409, f"claim {claim_id} failed to process")
            claim = ClaimFile.model_validate_json(row.graph)
            claim.status = decision
            updated = claim.model_dump_json()
            row.graph, row.status = updated, decision.value
            session.add(row)
            session.commit()
        return json.loads(updated)

    def _load(session: Session, claim_id: str) -> tuple[ClaimRow, ClaimFile]:
        row = session.get(ClaimRow, claim_id)
        if row is None or not row.graph or row.graph == "{}":
            raise HTTPException(404, f"claim {claim_id} not processed")
        if row.status == ClaimStatus.failed.value:
            raise HTTPException(409, f"claim {claim_id} failed to process")
        return row, ClaimFile.model_validate_json(row.graph)

    @app.post("/claims/{claim_id}/findings/{finding_id}/decision")
    def decide_finding(claim_id: str, finding_id: str, body: FindingDecisionIn) -> dict:
        """Confirm, dismiss or promote one review item; logged as verifier training data."""
        with Session(engine) as session:
            row, claim = _load(session, claim_id)
            finding = next((f for f in claim.findings if f.id == finding_id), None)
            if finding is None:
                raise HTTPException(404, f"finding {finding_id} not found")
            finding.decision = body.decision
            finding.decision_reason = body.reason
            if body.promote and finding.held_back:
                finding.held_back = False
                finding.origin = FindingOrigin.reviewer
                finding.verified_by.append("promoted by reviewer")
                finding.trail.append("Promoted to a review item by a reviewer.")
            claim.timeline = build_timeline(claim.documents, claim.findings)
            claim.evidence_map = build_evidence_map(claim.documents, claim.findings)
            row.graph = claim.model_dump_json()
            session.add(row)
            session.add(FindingDecisionRow(
                claim_id=claim_id, finding_id=finding_id, finding_type=finding.type.value,
                origin=finding.origin.value, verifier_score=finding.verifier_score,
                decision=body.decision.value, reason=body.reason, promoted=body.promote,
                reviewer=body.reviewer))
            session.commit()
            return json.loads(row.graph)

    @app.get("/claims/{claim_id}/checklist")
    def get_checklist(claim_id: str, lang: str = "en") -> dict:
        """The patient's fix-it checklist: verified, patient-facing, not-dismissed items."""
        with Session(engine) as session:
            row = session.get(ClaimRow, claim_id)
            if row is None:
                raise HTTPException(404, f"claim {claim_id} not found")
            if not row.graph or row.graph == "{}" or row.status == ClaimStatus.failed.value:
                return {"claim_id": claim_id, "lang": lang, "status": row.status,
                        "ready": False, "items": []}
            claim = ClaimFile.model_validate_json(row.graph)
            status = row.status
        out = checklist(claim, lang, llm)
        return {**out, "status": status, "ready": True,
                "audit_note": claim.audit.note if claim.audit else None}

    @app.post("/claims/{claim_id}/ask")
    def ask_claim(claim_id: str, body: AskIn) -> dict:
        """Claim chat: answers only from this claim's documents, with verified quotes."""
        from pipeline.m1_ingest import ingest_pdf
        from pipeline.m4_audit.agents import build_dossier

        with Session(engine) as session:
            _, claim = _load(session, claim_id)
        pdf_path = storage / f"{claim_id}.pdf"
        if not pdf_path.exists():
            raise HTTPException(404, f"claim {claim_id} pdf not found")
        ir = ingest_pdf(pdf_path, claim_id=claim_id)
        by_page = {p.page: p for p in ir.pages}
        texts = {d.document_id: " ".join(by_page[p].text for p in d.page_range if p in by_page)
                 for d in claim.documents}
        try:
            return ask(body.question, build_dossier(ir, claim.documents), texts, llm)
        except MissingFixture as exc:
            raise HTTPException(503, "Claim chat needs an AI model: set GEMINI_API_KEY or "
                                     "ANTHROPIC_API_KEY, and LLM_LIVE=1, on the API "
                                     "server.") from exc
        except (BudgetExceeded, LLMError, ValueError) as exc:
            raise HTTPException(503, f"Claim chat is unavailable right now ({exc}).") from exc

    @app.post("/claims/{claim_id}/approve")
    def approve_claim(claim_id: str, decision: DecisionIn | None = None) -> dict:
        return _decide(claim_id, ClaimStatus.approved)

    @app.post("/claims/{claim_id}/deny")
    def deny_claim(claim_id: str, decision: DecisionIn | None = None) -> dict:
        return _decide(claim_id, ClaimStatus.denied)

    return app


app = create_app()
