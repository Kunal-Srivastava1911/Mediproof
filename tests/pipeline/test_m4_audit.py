"""M4 audit engine: every injected fault raises its expected finding; clean files stay quiet."""

import pytest

from datagen import fake_data as fd
from pipeline.m1_ingest import ingest_pdf
from pipeline.m2_segment import segment_claim
from pipeline.m3_extract import extract_claim, ground_claim
from pipeline.m3_extract.confidence import rule_field
from pipeline.m4_audit import load_rules, run_audit
from schemas.claim import DocumentRecord
from schemas.common import DocType, Severity
from schemas.documents import ExtractedBillLine, ExtractedHospitalBill
from schemas.findings import FindingType
from schemas.ground_truth import FAULT_TO_FINDING, FaultType

# ---------------------------------------------------------------- config parity (fast)

def test_curated_markers_match_datagen():
    rules = {r["id"]: r for r in load_rules()["rules"]}
    markers = rules["drug_diagnosis_implausible"]["params"]["markers"]
    assert markers == fd.SPECIALTY_MARKER_DRUGS  # injection and detection can't drift


# ---------------------------------------------------------------- detector units (fast)

def _bill_record(lines=None, subtotal=100.0, discount=0.0, tax=5.0, total=105.0):
    e = ExtractedHospitalBill()
    e.subtotal, e.discount = rule_field(subtotal), rule_field(discount)
    e.tax, e.total = rule_field(tax), rule_field(total)
    for desc, qty, unit, amount in (lines or []):
        e.line_items.append(ExtractedBillLine(
            description=rule_field(desc), category=rule_field("procedure"),
            quantity=rule_field(qty), unit_price=rule_field(unit), amount=rule_field(amount)))
    return DocumentRecord(document_id="BILL", doc_type=DocType.hospital_bill,
                          page_range=[0], extracted=e)


def test_arithmetic_mismatch_fires_only_when_total_wrong():
    ok = run_audit([_bill_record(total=105.0)])
    assert not [f for f in ok if f.type == FindingType.bill_arithmetic_mismatch]
    bad = run_audit([_bill_record(total=999.0)])
    hit = [f for f in bad if f.type == FindingType.bill_arithmetic_mismatch]
    assert hit and hit[0].severity == Severity.warning


def test_inflated_and_duplicate_line_detection():
    rec = _bill_record(lines=[
        ("Surgeon Fee", 1, 20000.0, 20000.0),   # ok
        ("Room Rent", 3, 1000.0, 9000.0),        # inflated: 3*1000 != 9000
        ("Surgeon Fee", 1, 20000.0, 20000.0),    # duplicate of line 1
    ])
    types = {f.type for f in run_audit([rec])}
    assert FindingType.inflated_line_item in types
    assert FindingType.duplicate_line_item in types


def test_findings_use_review_item_language():
    for f in run_audit([_bill_record(total=999.0)]):
        assert "fraud" not in f.detail.lower() and "reject" not in f.detail.lower()
        assert "fraud" not in f.title.lower() and "reject" not in f.title.lower()


# ---------------------------------------------------------------- end-to-end (slow)

def _audit_for(rc):
    ir = ingest_pdf(rc.merged, claim_id=rc.claim.claim_id)
    recs = ground_claim(ir, extract_claim(ir, segment_claim(ir)))
    return run_audit(recs)


@pytest.mark.slow
@pytest.mark.parametrize("fault", [f.value for f in FaultType])
def test_each_injected_fault_raises_expected_finding(render_claim_factory, fault):
    rc = render_claim_factory(42, fault)
    injected = rc.claim.faults[0].fault_type          # actual fault (may fall back)
    expected = FAULT_TO_FINDING[injected]
    findings = _audit_for(rc)
    assert expected in {f.type for f in findings}, \
        f"{injected.value} did not raise {expected.value}; got {[f.type.value for f in findings]}"
    # the finding that matches carries evidence a human can click through to
    match = next(f for f in findings if f.type == expected)
    assert match.document_ids


@pytest.mark.slow
def test_clean_claim_has_no_warning_or_critical_findings(rendered_claim):
    findings = _audit_for(rendered_claim)
    severe = [f for f in findings if f.severity in (Severity.warning, Severity.critical)]
    assert not severe, f"false positives on a clean claim: {[f.type.value for f in severe]}"
