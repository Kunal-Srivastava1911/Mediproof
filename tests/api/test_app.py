"""API: health, upload→process→fetch, and reviewer corrections."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.service import _coerce, _resolve_field, apply_correction
from pipeline.m3_extract.confidence import rule_field
from schemas.claim import ClaimFile, Correction, DocumentRecord
from schemas.common import DocType
from schemas.documents import ExtractedHospitalBill


def _client(tmp_path) -> TestClient:
    app = create_app(database_url=f"sqlite:///{tmp_path / 'test.db'}",
                     storage_dir=str(tmp_path / "uploads"))
    return TestClient(app)


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
    assert len(graph["documents"]) == 6
    assert any(f["type"] == "inflated_line_item" for f in graph["findings"])
    assert graph["findings"][0]["evidence"], "finding carries clickable bbox evidence"

    listing = client.get("/claims").json()
    assert listing and listing[0]["claim_id"] == "CLAIM-42"

    bill_doc = graph["documents"][0]["document_id"]
    review = client.post("/claims/CLAIM-42/review", json={
        "document_id": bill_doc, "field_path": "patient.name",
        "new_value": "Reviewed Name", "reviewer": "qa"})
    assert review.status_code == 200
    updated = review.json()
    assert any(c["new_value"] == "Reviewed Name" for c in updated["corrections"])


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
