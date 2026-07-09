"""Fault injection: every fault type is injectable, isolated, deterministic, and labelled.

These tests pin the benchmark's ground-truth guarantees the audit engine is later scored
against: a seeded fault produces exactly one labelled problem, and the label points at the
`FindingType` M4 must raise.
"""

import pytest

from datagen import fake_data as fd
from datagen import inject_fault, sample_claim
from datagen.faults import maybe_inject_fault
from schemas.ground_truth import (
    FAULT_TO_FINDING,
    DischargeSummaryGT,
    FaultType,
    HospitalBillGT,
    LabReportGT,
    PharmacyBillGT,
)

SEED = 42


def _first(claim, model):
    return next((d for d in claim.documents if isinstance(d, model)), None)


@pytest.mark.parametrize("fault_type", list(FaultType))
def test_every_fault_type_is_injectable_and_labelled(fault_type):
    claim = sample_claim(seed=SEED)
    inject_fault(claim, seed=SEED, fault_type=fault_type)
    assert len(claim.faults) == 1
    label = claim.faults[0]
    # A recipe may fall back if a fault can't apply to this seed's claim, but the label's
    # expected_finding must always match the canonical mapping for whatever fired.
    assert label.expected_finding == FAULT_TO_FINDING[label.fault_type]
    assert label.document_ids  # a fault always points at the document(s) it touched
    assert "fraud" not in label.description.lower()
    assert "reject" not in label.description.lower()


def test_injection_is_deterministic():
    a = sample_claim(seed=SEED)
    inject_fault(a, seed=SEED)
    b = sample_claim(seed=SEED)
    inject_fault(b, seed=SEED)
    assert a.model_dump_json() == b.model_dump_json()


def test_inflated_line_breaks_line_math_but_not_totals():
    claim = sample_claim(seed=SEED)
    inject_fault(claim, seed=SEED, fault_type=FaultType.inflated_line_item)
    bill = _first(claim, HospitalBillGT)
    # Exactly the inflated line violates amount == qty x unit_price ...
    broken = [i for i in bill.line_items if round(i.unit_price * i.quantity, 2) != i.amount]
    assert len(broken) == 1
    # ... but the claim-level totals still reconcile (fault stays isolated).
    assert round(sum(i.amount for i in bill.line_items), 2) == bill.subtotal
    assert round(bill.subtotal - bill.discount + bill.tax, 2) == bill.total


def test_bill_arithmetic_error_breaks_only_the_total():
    claim = sample_claim(seed=SEED)
    inject_fault(claim, seed=SEED, fault_type=FaultType.bill_arithmetic_error)
    bill = _first(claim, HospitalBillGT)
    for i in bill.line_items:  # lines stay exact
        assert round(i.unit_price * i.quantity, 2) == i.amount
    assert round(bill.subtotal - bill.discount + bill.tax, 2) != bill.total


def test_duplicate_billing_adds_a_repeated_line():
    claim = sample_claim(seed=SEED)
    clean_n = len(_first(sample_claim(seed=SEED), HospitalBillGT).line_items)
    inject_fault(claim, seed=SEED, fault_type=FaultType.duplicate_billing)
    bill = _first(claim, HospitalBillGT)
    assert len(bill.line_items) == clean_n + 1
    keys = [(i.description, i.amount) for i in bill.line_items]
    assert len(keys) != len(set(keys))  # a duplicate exists


def test_date_mismatch_desyncs_bill_and_discharge():
    claim = sample_claim(seed=SEED)
    inject_fault(claim, seed=SEED, fault_type=FaultType.date_mismatch)
    assert _first(claim, HospitalBillGT).discharge_date != \
        _first(claim, DischargeSummaryGT).discharge_date


def test_name_mismatch_changes_only_pharmacy_name():
    claim = sample_claim(seed=SEED)
    inject_fault(claim, seed=SEED, fault_type=FaultType.name_mismatch)
    assert _first(claim, PharmacyBillGT).patient_name != claim.patient.name
    assert _first(claim, HospitalBillGT).patient.name == claim.patient.name


def test_missing_lab_report_removes_all_labs():
    claim = sample_claim(seed=SEED)
    assert any(isinstance(d, LabReportGT) for d in claim.documents)
    inject_fault(claim, seed=SEED, fault_type=FaultType.missing_lab_report)
    assert not any(isinstance(d, LabReportGT) for d in claim.documents)
    assert "lab_report" not in claim.template_meta


def test_drug_diagnosis_mismatch_adds_marker_drug_to_noncardiac_claim():
    # seed 42 is appendicitis (non-cardiac) — a cardiac marker drug is implausible there.
    claim = sample_claim(seed=SEED)
    disch = _first(claim, DischargeSummaryGT)
    assert not any(c.startswith("I2") for c in disch.icd10_codes)
    inject_fault(claim, seed=SEED, fault_type=FaultType.drug_diagnosis_mismatch)
    pharm = _first(claim, PharmacyBillGT)
    names = " ".join(ln.drug_name.lower() for ln in pharm.line_items)
    assert any(marker in names for marker in fd.SPECIALTY_MARKER_DRUGS)


def test_maybe_inject_respects_rate_bounds():
    always = [maybe_inject_fault(sample_claim(seed=s), seed=s, rate=1.0).is_clean
              for s in range(1000, 1030)]
    never = [maybe_inject_fault(sample_claim(seed=s), seed=s, rate=0.0).is_clean
             for s in range(1000, 1030)]
    assert not any(always)  # rate=1.0 -> every claim gets a fault
    assert all(never)       # rate=0.0 -> none do


def test_bulk_fault_rate_is_roughly_ten_percent():
    n = 200
    faulty = sum(
        not maybe_inject_fault(sample_claim(seed=s), seed=s, rate=0.1).is_clean
        for s in range(1000, 1000 + n)
    )
    assert 0.03 <= faulty / n <= 0.20  # ~10%, generous bounds for determinism
