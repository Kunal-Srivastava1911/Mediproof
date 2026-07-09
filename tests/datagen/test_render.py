"""datagen renderer: a claim renders to valid PDFs + a ground-truth answer key.

Marked slow because it launches headless Chromium.
"""

import json

import pytest

from datagen import sample_claim
from datagen.render import TEMPLATE_FOR, render_claim
from schemas import ClaimGroundTruth

pytestmark = pytest.mark.slow


def test_render_claim_produces_pdfs_and_ground_truth(tmp_path):
    claim = sample_claim(seed=42)
    manifest = render_claim(claim, tmp_path)

    # W1 DoD: at least the three templated doc types render.
    assert set(manifest["doc_types_rendered"]) >= {
        "hospital_bill", "discharge_summary", "pharmacy_bill"
    }

    merged = tmp_path / "claim.pdf"
    assert merged.exists() and merged.stat().st_size > 5000

    from pypdf import PdfReader
    n_rendered = sum(1 for d in claim.documents if d.doc_type in TEMPLATE_FOR)
    assert len(PdfReader(str(merged)).pages) == n_rendered

    for doc in manifest["documents"]:
        assert (tmp_path / doc["pdf"]).exists()

    # ground truth is valid and reloads to the same object
    gt = ClaimGroundTruth.model_validate_json((tmp_path / "ground_truth.json").read_text())
    assert gt.claim_id == claim.claim_id

    manifest_on_disk = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest_on_disk["claim_id"] == claim.claim_id
