"""M3.5 grounding: values map back to word boxes; ungrounded values are capped + flagged."""

import pytest

from pipeline.ir import PageIR, Token
from pipeline.m1_ingest import ingest_pdf
from pipeline.m2_segment import segment_claim
from pipeline.m3_extract import extract_claim, ground_claim, ground_field
from pipeline.m3_extract.confidence import rule_field
from schemas.common import BBox


def _tok(text, x0, y0, w=0.08, h=0.02):
    return Token(text=text, page=0, bbox=BBox(x0=x0, y0=y0, x1=x0 + w, y1=y0 + h))


# ---------------------------------------------------------------- unit (fast)

def test_grounds_multi_token_value_to_union_bbox():
    page = PageIR(page=0, width=595, height=842, is_digital=True, readability=1.0,
                  tokens=[_tok("Advik", 0.20, 0.30), _tok("Maharaj", 0.30, 0.30),
                          _tok("UHID", 0.60, 0.30)])
    field = rule_field("Advik Maharaj")
    ground_field(field, [page])
    assert len(field.evidence) == 1
    ev = field.evidence[0]
    assert ev.page == 0
    assert ev.bbox.x0 == pytest.approx(0.20) and ev.bbox.x1 == pytest.approx(0.38)  # union


def test_ungrounded_value_is_capped_and_flagged():
    page = PageIR(page=0, width=595, height=842, is_digital=True, readability=1.0,
                  tokens=[_tok("Totally", 0.2, 0.3), _tok("Different", 0.3, 0.3)])
    field = rule_field("Nonexistent Value")   # starts at 0.85
    ground_field(field, [page])
    assert not field.evidence
    assert field.confidence <= 0.5
    assert "ungrounded" in field.flags


def test_none_value_is_left_alone():
    from pipeline.m3_extract.confidence import missing_field
    f = missing_field()
    ground_field(f, [])
    assert f.value is None and not f.evidence and not f.flags


# ---------------------------------------------------------------- integration (slow)

@pytest.mark.slow
def test_most_fields_are_grounded_on_real_claim(rendered_claim):
    ir = ingest_pdf(rendered_claim.merged, claim_id="CLAIM-000042")
    recs = ground_claim(ir, extract_claim(ir, segment_claim(ir)))

    grounded = total = 0
    for rec in recs:
        for field_name in ("patient", "hospital_name", "admission_date", "total",
                           "diagnosis_text", "panel_name", "pharmacy_name"):
            f = getattr(rec.extracted, field_name, None)
            if f is None or not hasattr(f, "value") or f.value is None:
                continue
            total += 1
            if f.evidence:
                grounded += 1
                ev = f.evidence[0]
                assert 0.0 <= ev.bbox.x0 <= ev.bbox.x1 <= 1.0
                assert 0.0 <= ev.bbox.y0 <= ev.bbox.y1 <= 1.0
                assert ev.page in rec.page_range
    assert total and grounded / total >= 0.9   # nearly everything grounds on a digital claim


@pytest.mark.slow
def test_bill_amounts_ground_to_boxes(rendered_claim):
    ir = ingest_pdf(rendered_claim.merged, claim_id="CLAIM-000042")
    recs = ground_claim(ir, extract_claim(ir, segment_claim(ir)))
    bill = next(r.extracted for r in recs if r.doc_type.value == "hospital_bill")
    assert bill.total.evidence, "bill total must be grounded for click-to-source"
    assert all(li.amount.evidence for li in bill.line_items)
