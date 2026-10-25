"""API: health, upload→process→fetch, and reviewer corrections."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.patient import checklist
from api.service import _coerce, _resolve_field, apply_correction
from pipeline.m3_extract.confidence import rule_field
from pipeline.m3_extract.llm_client import LLMClient
from schemas.claim import ClaimFile, Correction, DocumentRecord
from schemas.common import DocType, Severity
from schemas.documents import ExtractedHospitalBill
from schemas.findings import Finding, FindingDecision, FindingOrigin, FindingType, ProofQuote


def _client(tmp_path) -> TestClient:
    # Replay-only client over an empty fixture dir: tests never make live Claude calls.
    app = create_app(database_url=f"sqlite:///{tmp_path / 'test.db'}",
                     storage_dir=str(tmp_path / "uploads"),
                     llm_client=LLMClient(tmp_path / "llm", live=False))
    return TestClient(app)


def _finding(fid, **kw):
    base = dict(id=fid, type=FindingType.date_inconsistent, severity=Severity.warning,
                title="t", detail=f"detail {fid}", document_ids=["D1"])
    return Finding(**{**base, **kw})


def test_checklist_shows_only_verified_patient_items(tmp_path):
    claim = ClaimFile(claim_id="C1", documents=[
        DocumentRecord(document_id="D1", doc_type=DocType.claim_form, page_range=[0])])
    claim.findings = [
        _finding("F-001", origin=FindingOrigin.agent,
                 proof=[ProofQuote(document_id="D1", quote="Date of Admission 06/09/2024",
                                   grounded=True)]),
        _finding("F-002", held_back=True, origin=FindingOrigin.agent),
        _finding("F-003", type=FindingType.non_payable_consumable, severity=Severity.info,
                 patient_facing=False),
        _finding("F-004", decision=FindingDecision.dismissed),
    ]
    en = checklist(claim, "en", LLMClient(tmp_path, live=False))
    assert [i["id"] for i in en["items"]] == ["F-001"]
    item = en["items"][0]
    assert item["sources"][0]["quote"] == "Date of Admission 06/09/2024"
    assert item["sources"][0]["label"] == "Claim form"
    hi = checklist(claim, "hi", LLMClient(tmp_path, live=False))
    assert hi["items"][0]["title"] == "आपके दस्तावेज़ों में तारीखें मेल नहीं खातीं"
    assert hi["detail_translated"] is False   # offline: English detail kept, and flagged
    for text in (item["title"], item["action"], hi["items"][0]["action"]):
        assert "fraud" not in text.lower() and "reject" not in text.lower()


# ---------------------------------------------------------------- unit (fast)

def test_coerce_matches_existing_type():
    assert _coerce("55000.50", 1.0) == 55000.50
    assert _coerce("2024-09-09", date(2020, 1, 1)) == date(2024, 9, 9)
    assert _coerce("Jane Doe", "Old Name") == "Jane Doe"


def test_resolve_and_apply_correction():
    e = ExtractedHospitalBill()
    e.patient.name = rule_field("Wrong Name")
    claim = ClaimFile(claim_id="C1", documents=[
        DocumentRecord(document_id="D1", doc_type=DocType.hospital_bill,
                       page_range=[0], extracted=e)])
    assert _resolve_field(e, "patient.name").value == "Wrong Name"
    logged = apply_correction(claim, Correction(
        document_id="D1", field_path="patient.name", new_value="Right Name", reviewer="qa"))
    assert e.patient.name.value == "Right Name"
    assert e.patient.name.confidence == 1.0
    assert "reviewer_corrected" in e.patient.name.flags
    assert logged.old_value == "Wrong Name" and claim.corrections


def test_healthz_and_404(tmp_path):
    client = _client(tmp_path)
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/claims/nope").status_code == 404


def test_status_unknown_is_404(tmp_path):
    client = _client(tmp_path)
    assert client.get("/claims/nope/status").status_code == 404


def test_approve_unknown_is_404(tmp_path):
    client = _client(tmp_path)
    assert client.post("/claims/nope/approve").status_code == 404


# ---------------------------------------------------------------- integration (slow)

@pytest.mark.slow
def test_upload_process_fetch_and_review(tmp_path, rendered_claim, render_claim_factory):
    client = _client(tmp_path)
    faulty = render_claim_factory(42, "inflated_line_item")
    with open(faulty.merged, "rb") as fh:
        resp = client.post("/claims", params={"claim_id": "CLAIM-42"},
                           files={"file": ("claim.pdf", fh, "application/pdf")})
    assert resp.status_code == 202 and resp.json()["status"] == "processing"

    graph = client.get("/claims/CLAIM-42").json()
    assert graph["status"] == "needs_review"            # inflated line -> flagged
    assert len(graph["documents"]) == len(faulty.claim.documents)
    assert any(f["type"] == "inflated_line_item" for f in graph["findings"])
    assert graph["findings"][0]["evidence"], "finding carries clickable bbox evidence"

    listing = client.get("/claims").json()
    assert listing and listing[0]["claim_id"] == "CLAIM-42"

    bill_doc = next(d["document_id"] for d in graph["documents"]
                    if d["doc_type"] == "hospital_bill")
    review = client.post("/claims/CLAIM-42/review", json={
        "document_id": bill_doc, "field_path": "patient.name",
        "new_value": "Reviewed Name", "reviewer": "qa"})
    assert review.status_code == 200
    updated = review.json()
    assert any(c["new_value"] == "Reviewed Name" for c in updated["corrections"])


@pytest.mark.slow
def test_checklist_decisions_and_offline_chat(tmp_path, render_claim_factory):
    client = _client(tmp_path)
    rc = render_claim_factory(42, "claim_form_date_mismatch")
    with open(rc.merged, "rb") as fh:
        client.post("/claims", params={"claim_id": "CLAIM-CF"},
                    files={"file": ("claim.pdf", fh, "application/pdf")})

    listing = client.get("/claims/CLAIM-CF/checklist").json()
    assert listing["ready"] and "no recorded Claude responses" in listing["audit_note"]
    titles = [i["title"] for i in listing["items"]]
    assert "Dates don't match across your documents" in titles
    assert all(i["sources"] and i["sources"][0]["page"] is not None for i in listing["items"])

    graph = client.get("/claims/CLAIM-CF").json()
    assert graph["timeline"] and graph["evidence_map"]
    assert any(ev["conflict"] for ev in graph["timeline"])
    fid = next(f["id"] for f in graph["findings"] if f["rule_id"] == "claim_form_dates")
    resp = client.post(f"/claims/CLAIM-CF/findings/{fid}/decision",
                       json={"decision": "dismissed", "reason": "claim form already fixed"})
    assert resp.status_code == 200
    after = client.get("/claims/CLAIM-CF/checklist").json()
    assert fid not in [i["id"] for i in after["items"]]

    chat = client.post("/claims/CLAIM-CF/ask", json={"question": "Why is my date flagged?"})
    assert chat.status_code == 503 and "ANTHROPIC_API_KEY" in chat.json()["detail"]


@pytest.mark.slow
def test_status_reflects_processing_result(tmp_path, render_claim_factory):
    client = _client(tmp_path)
    rc = render_claim_factory(42)
    with open(rc.merged, "rb") as fh:
        client.post("/claims", params={"claim_id": "CLAIM-S"},
                    files={"file": ("claim.pdf", fh, "application/pdf")})
    status = client.get("/claims/CLAIM-S/status")
    assert status.status_code == 200
    body = status.json()
    assert body["claim_id"] == "CLAIM-S" and "status" in body
    # TestClient runs BackgroundTasks synchronously, so the row status now matches the graph.
    assert body["status"] == client.get("/claims/CLAIM-S").json()["status"]


@pytest.mark.slow
def test_approve_persists_status(tmp_path, render_claim_factory):
    client = _client(tmp_path)
    rc = render_claim_factory(42)
    with open(rc.merged, "rb") as fh:
        client.post("/claims", params={"claim_id": "CLAIM-A"},
                    files={"file": ("claim.pdf", fh, "application/pdf")})
    resp = client.post("/claims/CLAIM-A/approve")
    assert resp.status_code == 200 and resp.json()["status"] == "approved"
    assert client.get("/claims/CLAIM-A/status").json()["status"] == "approved"


@pytest.mark.slow
def test_deny_persists_status(tmp_path, render_claim_factory):
    client = _client(tmp_path)
    rc = render_claim_factory(42)
    with open(rc.merged, "rb") as fh:
        client.post("/claims", params={"claim_id": "CLAIM-D"},
                    files={"file": ("claim.pdf", fh, "application/pdf")})
    resp = client.post("/claims/CLAIM-D/deny")
    assert resp.status_code == 200 and resp.json()["status"] == "denied"
    assert client.get("/claims/CLAIM-D/status").json()["status"] == "denied"


@pytest.mark.slow
def test_page_image_renders_png(tmp_path, render_claim_factory):
    client = _client(tmp_path)
    rc = render_claim_factory(42)
    with open(rc.merged, "rb") as fh:
        client.post("/claims", params={"claim_id": "CLAIM-IMG"},
                    files={"file": ("claim.pdf", fh, "application/pdf")})
    img = client.get("/claims/CLAIM-IMG/pages/0.png")
    assert img.status_code == 200
    assert img.headers["content-type"] == "image/png"
    assert img.content[:8] == b"\x89PNG\r\n\x1a\n"       # valid PNG for the bbox overlay
    assert client.get("/claims/CLAIM-IMG/pages/99.png").status_code == 404


@pytest.mark.slow
def test_review_unknown_field_is_422(tmp_path, render_claim_factory):
    client = _client(tmp_path)
    rc = render_claim_factory(42)
    with open(rc.merged, "rb") as fh:
        client.post("/claims", params={"claim_id": "CLAIM-C"},
                    files={"file": ("claim.pdf", fh, "application/pdf")})
    bad = client.post("/claims/CLAIM-C/review", json={
        "document_id": "does-not-exist", "field_path": "patient.name", "new_value": "x"})
    assert bad.status_code == 422
