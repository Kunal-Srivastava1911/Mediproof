"""M3 deterministic extraction: field fidelity vs ground truth + validator confidence."""

import pytest

from pipeline.m1_ingest import ingest_pdf
from pipeline.m2_segment import segment_claim
from pipeline.m3_extract import extract_claim, extract_document
from schemas.common import DocType, FieldSource
from schemas.ground_truth import (
    DischargeSummaryGT,
    HospitalBillGT,
    LabReportGT,
    PharmacyBillGT,
    PrescriptionGT,
)

# ---------------------------------------------------------------- unit (fast)

def test_other_type_has_no_extractor():
    assert extract_document(DocType.other, "anything") is None


def test_bill_row_parsing_and_validators():
    text = "\n".join([
        "Acme Hospital IN-PATIENT BILL",
        "Patient Name Jane Doe UHID UHID001234",
        "Age / Sex 40 / F Bill No INV/1",
        "Admission Date 01 Jan 2025 Discharge Date 05 Jan 2025",
        "# Description Category Qty Unit (Rs) Amount (Rs)",
        "1 Room Rent room 4 1000.00 4000.00",
        "2 Surgeon Fee procedure 1 20000.00 20000.00",
        "Subtotal Rs 24000.00",
        "Discount Rs 0.00",
        "Tax (5%) Rs 1200.00",
        "Total Payable Rs 25200.00",
    ])
    doc = extract_document(DocType.hospital_bill, text)
    assert doc.patient.name.value == "Jane Doe"
    assert doc.patient.age.value == 40
    assert doc.patient.gender.value == "F"
    assert doc.hospital_name.value == "Acme Hospital"
    assert len(doc.line_items) == 2
    assert doc.line_items[0].amount.value == 4000.00
    # subtotal reconciles with line amounts -> validated (green)
    assert doc.subtotal.value == 24000.00
    assert doc.subtotal.confidence >= 0.9
    assert doc.subtotal.source == FieldSource.rule
    # admission < discharge -> date-logic validator passed
    assert doc.admission_date.confidence >= 0.9


def test_icd10_format_validator():
    text = "Acme DISCHARGE SUMMARY\nFinal Diagnosis\nSomething\nICD-10: K35.80, NOTACODE"
    doc = extract_document(DocType.discharge_summary, text)
    codes = {c.value: c for c in doc.icd10_codes}
    assert codes["K35.80"].confidence >= 0.9      # valid format -> validated
    assert codes["NOTACODE"].confidence < 0.9     # invalid -> unvalidated


# ---------------------------------------------------------------- fidelity (slow)

def _by_id(claim):
    return {d.document_id: d for d in claim.documents}


@pytest.mark.slow
def test_extraction_matches_ground_truth(rendered_claim):
    ir = ingest_pdf(rendered_claim.merged, claim_id="CLAIM-000042")
    recs = extract_claim(ir, segment_claim(ir))
    claim = rendered_claim.claim

    # documents come out in page order == claim.documents order
    gts = claim.documents
    assert len(recs) == len(gts)

    for rec, gt in zip(recs, gts, strict=True):
        e = rec.extracted
        assert e is not None and e.doc_type == gt.doc_type
        if isinstance(gt, HospitalBillGT):
            assert e.patient.name.value == gt.patient.name
            assert e.patient.age.value == gt.patient.age
            assert e.admission_date.value == gt.admission_date
            assert e.discharge_date.value == gt.discharge_date
            assert len(e.line_items) == len(gt.line_items)
            assert e.total.value == gt.total
            assert e.line_items[0].amount.value == gt.line_items[0].amount
        elif isinstance(gt, DischargeSummaryGT):
            assert e.diagnosis_text.value == gt.diagnosis_text
            assert [c.value for c in e.icd10_codes] == gt.icd10_codes
            assert e.treating_doctor.value == gt.treating_doctor
        elif isinstance(gt, PharmacyBillGT):
            assert e.patient_name.value == gt.patient_name
            assert len(e.line_items) == len(gt.line_items)
            assert e.total.value == gt.total
            assert e.line_items[0].drug_name.value == gt.line_items[0].drug_name
        elif isinstance(gt, PrescriptionGT):
            assert [m.value for m in e.medications] == [m.drug_name for m in gt.medications]
            assert e.doctor.value == gt.doctor
        elif isinstance(gt, LabReportGT):
            assert e.panel_name.value == gt.panel_name
            assert e.results[0].value.value == gt.results[0].value


@pytest.mark.slow
def test_most_fields_land_in_green_band(rendered_claim):
    ir = ingest_pdf(rendered_claim.merged, claim_id="CLAIM-000042")
    recs = extract_claim(ir, segment_claim(ir))
    confs = []
    for rec in recs:
        e = rec.extracted
        for name in ("patient", "hospital_name", "total", "diagnosis_text", "panel_name"):
            f = getattr(e, name, None)
            if f is not None and hasattr(f, "confidence") and f.value is not None:
                confs.append(f.confidence)
    assert confs and min(confs) >= 0.5  # nothing red; deterministic layer is confident
