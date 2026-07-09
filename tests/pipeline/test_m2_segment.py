"""M2 segmentation: page classification accuracy + one document per rendered page."""

import pytest

from pipeline.ir import ClaimIR, PageIR
from pipeline.m1_ingest import ingest_pdf
from pipeline.m2_segment import classify_page, segment_claim
from schemas.common import DocType


def _page(text: str, page: int = 0, unreadable: bool = False) -> PageIR:
    return PageIR(page=page, width=595, height=842, is_digital=not unreadable,
                  readability=0.0 if unreadable else 1.0, unreadable=unreadable, text=text)


# ---------------------------------------------------------------- classify (fast)

def test_classify_titles_to_types():
    cases = {
        "Final In-Patient Bill ... Total Payable 100": DocType.hospital_bill,
        "Discharge Summary ... Final Diagnosis ... Course in Hospital": DocType.discharge_summary,
        "Pharmacy Invoice ... Batch MRP Rx Ref": DocType.pharmacy_bill,
        "Laboratory Report ... Reference Range Panel": DocType.lab_report,
        "Prescription (Rx) ... Prescribing Doctor Frequency Duration": DocType.prescription,
    }
    for text, expected in cases.items():
        dt, conf = classify_page(_page(text))
        assert dt == expected
        assert conf >= 0.8


def test_unknown_page_is_other_with_low_confidence():
    dt, conf = classify_page(_page("hello world, nothing to classify here"))
    assert dt == DocType.other
    assert conf < 0.5


def test_segment_skips_unreadable_pages():
    ir = ClaimIR(claim_id="C1", source_pdf="x", pages=[
        _page("Final In-Patient Bill Total Payable", page=0),
        _page("", page=1, unreadable=True),
        _page("Pharmacy Invoice MRP Batch", page=2),
    ])
    docs = segment_claim(ir)
    assert [d.doc_type for d in docs] == [DocType.hospital_bill, DocType.pharmacy_bill]
    assert all(d.page_range for d in docs)


# ---------------------------------------------------------------- integration (slow)

@pytest.mark.slow
def test_segments_rendered_claim_into_correct_types(rendered_claim):
    ir = ingest_pdf(rendered_claim.merged, claim_id="CLAIM-000042")
    docs = segment_claim(ir)

    # One document per rendered page, in order, each classified to its true type.
    expected = [d["doc_type"] for d in rendered_claim.manifest["documents"]]
    assert [d.doc_type.value for d in docs] == expected
    assert all(d.classifier_confidence >= 0.8 for d in docs)
    # page ranges partition the readable pages exactly once
    covered = [p for d in docs for p in d.page_range]
    assert covered == sorted(covered)
    assert len(covered) == len(ir.readable_pages)
