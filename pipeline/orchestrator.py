"""End-to-end pipeline: a claim PDF in, an assembled `ClaimFile` out.

Composes the modules in order — M1 ingest → M2 segment → M3 extract → M3 LLM fallback →
M3.5 ground → M4 audit → M5 completeness — and packs the result into the runtime claim graph
the API returns and the dashboard renders. Deterministic and offline: the LLM fallback runs
through the record/replay client, so a missing fixture just leaves rule values in place.
"""

from __future__ import annotations

from pathlib import Path

from pipeline.m1_ingest import ingest_pdf, page_infos
from pipeline.m2_segment import segment_claim
from pipeline.m3_extract import apply_llm_fallback, extract_claim, ground_claim
from pipeline.m3_extract.grounding import _walk_fields
from pipeline.m3_extract.llm_client import LLMClient
from pipeline.m4_audit import run_audit
from pipeline.m5_complete import complete_claim
from schemas.claim import ClaimFile, ClaimStatus
from schemas.common import AMBER_THRESHOLD, Severity

DEFAULT_CLAIM_TYPE = "cashless_hospitalization"


def _has_red_field(extracted) -> bool:
    """True if any extracted field landed in the red band (mandatory review)."""
    return any(
        f.value is not None and f.confidence < AMBER_THRESHOLD
        for f in _walk_fields(extracted)
    )


def run_pipeline(
    pdf_path: str | Path,
    claim_id: str | None = None,
    claim_type: str = DEFAULT_CLAIM_TYPE,
    *,
    llm_client: LLMClient | None = None,
) -> ClaimFile:
    """Run the full pipeline on one claim PDF and return the assembled claim graph."""
    pdf_path = Path(pdf_path)
    claim_id = claim_id or pdf_path.stem
    client = llm_client or LLMClient()

    ir = ingest_pdf(pdf_path, claim_id=claim_id)
    records = segment_claim(ir)
    extract_claim(ir, records)
    for rec in records:
        if rec.extracted is not None:
            context = "\n".join(ir.pages[p].text for p in rec.page_range if p < len(ir.pages))
            apply_llm_fallback(rec.extracted, client, context)
    ground_claim(ir, records)

    findings = run_audit(records)
    completeness = complete_claim(claim_type, records)

    needs_review = any(f.severity in (Severity.warning, Severity.critical) for f in findings) \
        or any(p.unreadable for p in ir.pages) \
        or any(_has_red_field(r.extracted) for r in records if r.extracted is not None)

    return ClaimFile(
        claim_id=claim_id,
        status=ClaimStatus.needs_review if needs_review else ClaimStatus.processed,
        pages=page_infos(ir),
        documents=records,
        findings=findings,
        completeness=completeness,
    )
