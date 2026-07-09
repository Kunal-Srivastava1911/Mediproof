"""M5 completeness: required/present/missing matrix per claim type."""

import pytest

from pipeline.m1_ingest import ingest_pdf
from pipeline.m2_segment import segment_claim
from pipeline.m5_complete import check_completeness, complete_claim, required_for
from schemas.common import DocType


def test_complete_cashless_claim_has_no_missing():
    present = [DocType.hospital_bill, DocType.discharge_summary, DocType.pharmacy_bill,
               DocType.lab_report, DocType.prescription]
    report = check_completeness("cashless_hospitalization", present)
    assert report.missing == []
    assert set(report.present) == set(report.required)


def test_missing_documents_are_reported():
    present = [DocType.hospital_bill, DocType.discharge_summary]
    report = check_completeness("cashless_hospitalization", present)
    assert DocType.lab_report in report.missing
    assert DocType.pharmacy_bill in report.missing
    assert DocType.hospital_bill in report.present


def test_unknown_claim_type_uses_default():
    assert required_for("something_new") == [DocType.hospital_bill, DocType.discharge_summary]


@pytest.mark.slow
def test_complete_claim_from_segmented_docs(rendered_claim):
    ir = ingest_pdf(rendered_claim.merged, claim_id="CLAIM-000042")
    report = complete_claim("cashless_hospitalization", segment_claim(ir))
    assert report.missing == []          # a clean cashless claim has every required doc


@pytest.mark.slow
def test_missing_lab_fault_shows_up_in_completeness(render_claim_factory):
    rc = render_claim_factory(42, "missing_lab_report")
    ir = ingest_pdf(rc.merged, claim_id="CLAIM-000042")
    report = complete_claim("cashless_hospitalization", segment_claim(ir))
    assert DocType.lab_report in report.missing
