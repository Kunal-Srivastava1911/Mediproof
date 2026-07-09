"""datagen sampler: determinism + coherence invariants for *clean* claims."""

import json

import pytest

from datagen import fake_data as fd
from datagen import sample_claim
from schemas import DischargeSummaryGT, HospitalBillGT, PharmacyBillGT

GOLDEN_SEED = 42


def _docs_by_type(claim, model):
    return [d for d in claim.documents if isinstance(d, model)]


def test_determinism_same_seed_same_bytes():
    a = sample_claim(seed=123).model_dump_json()
    b = sample_claim(seed=123).model_dump_json()
    assert a == b


def test_different_seeds_differ():
    assert sample_claim(seed=1).model_dump_json() != sample_claim(seed=2).model_dump_json()


def test_bill_arithmetic_is_exact():
    bill = _docs_by_type(sample_claim(seed=GOLDEN_SEED), HospitalBillGT)[0]
    assert round(sum(i.amount for i in bill.line_items), 2) == bill.subtotal
    assert round(bill.subtotal - bill.discount + bill.tax, 2) == bill.total
    for item in bill.line_items:
        assert round(item.unit_price * item.quantity, 2) == item.amount


def test_dates_are_coherent():
    claim = sample_claim(seed=GOLDEN_SEED)
    bill = _docs_by_type(claim, HospitalBillGT)[0]
    disch = _docs_by_type(claim, DischargeSummaryGT)[0]
    pharm = _docs_by_type(claim, PharmacyBillGT)[0]
    assert bill.admission_date < bill.discharge_date
    assert disch.admission_date == bill.admission_date
    assert disch.discharge_date == bill.discharge_date
    assert bill.admission_date <= pharm.bill_date <= bill.discharge_date


def test_patient_consistent_across_documents():
    claim = sample_claim(seed=GOLDEN_SEED)
    canonical = claim.patient.name
    assert _docs_by_type(claim, HospitalBillGT)[0].patient.name == canonical
    assert _docs_by_type(claim, DischargeSummaryGT)[0].patient.name == canonical
    assert _docs_by_type(claim, PharmacyBillGT)[0].patient_name == canonical


def test_pharmacy_drugs_belong_to_a_scenario():
    claim = sample_claim(seed=GOLDEN_SEED)
    pharm = _docs_by_type(claim, PharmacyBillGT)[0]
    known_drug_names = {f"{d.name} {d.strength}" for d in fd.DRUGS.values()}
    for line in pharm.line_items:
        assert line.drug_name in known_drug_names


def test_clean_claim_has_no_faults():
    claim = sample_claim(seed=GOLDEN_SEED)
    assert claim.faults == []
    assert claim.is_clean


def test_matches_golden(golden_dir):
    golden_path = golden_dir / "datagen" / f"claim_seed{GOLDEN_SEED}.json"
    if not golden_path.exists():
        pytest.skip(f"golden not generated yet: {golden_path}")
    expected = json.loads(golden_path.read_text(encoding="utf-8"))
    actual = sample_claim(seed=GOLDEN_SEED).model_dump(mode="json")
    assert actual == expected
