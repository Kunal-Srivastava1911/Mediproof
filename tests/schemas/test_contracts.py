"""Contract sanity tests for schemas/ — these guard the single source of truth."""

from datagen import sample_claim
from schemas import (
    AMBER_THRESHOLD,
    GREEN_THRESHOLD,
    ClaimGroundTruth,
    ConfidenceBand,
    ExtractedField,
    band_for,
)


def test_band_thresholds():
    assert band_for(GREEN_THRESHOLD) is ConfidenceBand.green
    assert band_for(0.99) is ConfidenceBand.green
    assert band_for(AMBER_THRESHOLD) is ConfidenceBand.amber
    assert band_for(0.79) is ConfidenceBand.amber
    assert band_for(0.49) is ConfidenceBand.red
    assert band_for(0.0) is ConfidenceBand.red


def test_extracted_field_default_is_not_extracted():
    f: ExtractedField[str] = ExtractedField()
    assert f.value is None
    assert f.confidence == 0.0
    assert f.band is ConfidenceBand.red
    assert f.evidence == []


def test_claim_ground_truth_roundtrips():
    claim = sample_claim(seed=7)
    reloaded = ClaimGroundTruth.model_validate_json(claim.model_dump_json())
    assert reloaded.model_dump(mode="json") == claim.model_dump(mode="json")


def test_document_union_preserves_doc_type_on_reload():
    claim = sample_claim(seed=7)
    reloaded = ClaimGroundTruth.model_validate_json(claim.model_dump_json())
    original_types = [d.doc_type for d in claim.documents]
    reloaded_types = [d.doc_type for d in reloaded.documents]
    assert original_types == reloaded_types
