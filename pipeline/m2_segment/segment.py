"""M2 — Page-stream segmentation + document classification.

Splits the ingested page stream into typed documents (`DocumentRecord`s). This is the **P0**
classifier from plan §M2: a transparent keyword/heuristic baseline over each page's OCR text
— cheap, no GPU, and a solid floor. The staged upgrades (P1 sentence-transformer embeddings,
P2 LayoutLMv3+LoRA) plug in behind the same `classify_page` interface if metrics demand.

Boundary detection: a new document begins when the page class changes or a "first-page cue"
(a letterhead doc-title) appears — so a multi-page document stays whole while back-to-back
documents of the same type are still split.
"""

from __future__ import annotations

from pipeline.ir import ClaimIR, PageIR
from schemas.claim import DocumentRecord
from schemas.common import DocType

# Per-type keyword weights over lowercased page text. Document titles carry the most weight;
# body-field cues break ties. Overlapping cues ("medication", "diagnosis") are fine because
# the title cue dominates.
DOC_KEYWORDS: dict[DocType, dict[str, int]] = {
    DocType.hospital_bill: {
        "in-patient bill": 4, "final in-patient bill": 2, "total payable": 3,
        "bill no": 1, "subtotal": 2, "non-payable": 1, "billing officer": 1,
    },
    DocType.discharge_summary: {
        "discharge summary": 4, "final diagnosis": 3, "course in hospital": 3,
        "advice on discharge": 2, "treating doctor": 2, "procedures performed": 2,
    },
    DocType.pharmacy_bill: {
        "pharmacy invoice": 4, "pharmacy": 1, "rx ref": 2, "mrp": 3, "batch": 2,
        "pharmacist": 1,
    },
    DocType.lab_report: {
        "laboratory report": 4, "lab report": 2, "reference range": 3, "panel": 2,
        "consultant pathologist": 2, "referring doctor": 1,
    },
    DocType.prescription: {
        "prescription (rx)": 4, "prescription": 2, "prescribing doctor": 3,
        "frequency": 2, "duration": 2, "complete the full course": 1,
    },
}

# Title cues that mark the first page of a document (boundary signal).
_FIRST_PAGE_CUES = (
    "in-patient bill", "discharge summary", "pharmacy invoice",
    "laboratory report", "lab report", "prescription",
)


def classify_page(page: PageIR) -> tuple[DocType, float]:
    """Return the most likely `DocType` for one page and a confidence in [0,1]."""
    text = page.text.lower()
    scores = {
        dt: sum(w for kw, w in kws.items() if kw in text)
        for dt, kws in DOC_KEYWORDS.items()
    }
    winner = max(scores, key=scores.get)
    best = scores[winner]
    if best == 0:
        return DocType.other, 0.25

    total = sum(scores.values())
    runner_up = max((s for dt, s in scores.items() if dt != winner), default=0)
    # Confidence blends how dominant the winner is over the field (best/total) with its
    # margin over the runner-up; a matched title cue floors it into the green band.
    share = best / total
    margin = (best - runner_up) / best
    conf = 0.5 * share + 0.5 * (0.5 + 0.5 * margin)
    if any(cue in text for cue in _FIRST_PAGE_CUES):
        conf = max(conf, 0.85)
    return winner, round(min(conf, 0.99), 4)


def _has_first_page_cue(page: PageIR) -> bool:
    text = page.text.lower()
    return any(cue in text for cue in _FIRST_PAGE_CUES)


def segment_claim(claim_ir: ClaimIR) -> list[DocumentRecord]:
    """Group the page stream into typed `DocumentRecord`s (M2 output for the claim graph)."""
    records: list[DocumentRecord] = []
    confidences: list[list[float]] = []

    for page in claim_ir.pages:
        if page.unreadable:
            continue  # excluded from auto-accept (M1 quality gate); not assigned a document
        doc_type, conf = classify_page(page)
        starts_new = (
            not records
            or doc_type != records[-1].doc_type
            or _has_first_page_cue(page)
        )
        if starts_new:
            records.append(DocumentRecord(
                document_id=f"{claim_ir.claim_id}-DOC{len(records) + 1:02d}",
                doc_type=doc_type, page_range=[page.page], classifier_confidence=conf,
            ))
            confidences.append([conf])
        else:
            records[-1].page_range.append(page.page)
            confidences[-1].append(conf)

    # A multi-page document's confidence is the mean over its pages.
    for rec, confs in zip(records, confidences, strict=True):
        rec.classifier_confidence = round(sum(confs) / len(confs), 4)
    return records
