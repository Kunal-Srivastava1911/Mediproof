"""M1 ingest: digital text-layer extraction, watermark masking, and the quality gate."""

import pdfplumber
import pytest

from pipeline.ir import PageIR, Token
from pipeline.m1_ingest import QUALITY_THRESHOLD, ingest_pdf, page_infos, page_readability
from schemas.common import BBox

# ---------------------------------------------------------------- pure unit tests (fast)

def test_readability_rises_with_coverage_and_confidence():
    assert page_readability(0, 1.0) < page_readability(30, 1.0)
    assert page_readability(30, 0.3) < page_readability(30, 1.0)
    assert page_readability(100, 1.0) == pytest.approx(1.0, abs=1e-6)


def test_line_texts_group_tokens_by_row():
    def tok(text, x0, y0):
        return Token(text=text, page=0,
                     bbox=BBox(x0=x0, y0=y0, x1=x0 + 0.05, y1=y0 + 0.01))
    page = PageIR(page=0, width=100, height=100, is_digital=True, readability=1.0,
                  tokens=[tok("Patient", 0.1, 0.20), tok("Name", 0.2, 0.201),
                          tok("Total", 0.1, 0.50)])
    lines = page.line_texts()
    assert "Patient Name" in lines
    assert "Total" in lines


# ---------------------------------------------------------------- integration (slow)

@pytest.mark.slow
def test_ingest_reads_every_page_as_digital(rendered_claim):
    ir = ingest_pdf(rendered_claim.merged, claim_id="CLAIM-000042")
    assert len(ir.pages) == len(rendered_claim.manifest["documents"])
    for p in ir.pages:
        assert p.is_digital
        assert not p.unreadable
        assert p.readability >= QUALITY_THRESHOLD
        assert p.tokens, "a digital page must yield word tokens"
        # boxes are normalized
        for t in p.tokens[:5]:
            assert 0.0 <= t.bbox.x0 <= t.bbox.x1 <= 1.0
            assert 0.0 <= t.bbox.y0 <= t.bbox.y1 <= 1.0


@pytest.mark.slow
def test_watermark_is_masked_out(rendered_claim):
    from pipeline.m1_ingest.ingest import is_rotated_char

    def lone_letters(texts):
        return [t for t in texts if len(t) == 1 and t.isalpha()]

    # Unmasked, the diagonal watermark shatters into ~20 scattered single-letter "words" ...
    with pdfplumber.open(str(rendered_claim.merged)) as pdf:
        assert any(is_rotated_char(c) for c in pdf.pages[0].chars)  # watermark present
        raw_lone = lone_letters([w["text"] for w in pdf.pages[0].extract_words()])

    # ... ingest masks the watermark region (plan §5), removing the bulk of them.
    ir = ingest_pdf(rendered_claim.merged)
    ingest_lone = lone_letters([t.text for t in ir.pages[0].tokens])
    assert len(ingest_lone) <= len(raw_lone) - 15


@pytest.mark.slow
def test_key_fields_survive_ingest(rendered_claim):
    ir = ingest_pdf(rendered_claim.merged)
    all_text = "\n".join(p.text for p in ir.pages)
    assert "Patient Name" in all_text
    assert rendered_claim.claim.patient.name in all_text
    assert "Total" in all_text


@pytest.mark.slow
def test_page_infos_projects_public_contract(rendered_claim):
    ir = ingest_pdf(rendered_claim.merged)
    infos = page_infos(ir)
    assert len(infos) == len(ir.pages)
    assert all(i.is_digital and not i.unreadable for i in infos)
