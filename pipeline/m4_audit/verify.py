"""Proof-carrying verification of agent proposals → `Finding`s.

A proposal becomes a review item only through three independent checks:

1. **Grounding** — every quote must appear in the document it cites (fuzzy match against
   that document's text) and is located on the page (bbox evidence). An ungrounded quote
   means the finding cannot be shown to anyone as evidence: it scores 0 and is held back.
2. **Code check** — a proposal that names dates, counts or a missing report is re-checked
   deterministically (`check_kind`): the dates must really differ, the date must really fall
   outside the window, the counts must really differ, the keyword must really be absent from
   every other document.
3. **Skeptic** — a second agent's upheld/rejected verdict.

These combine into `verifier_score`; items below the calibrated threshold
(`calibration.json`, produced by `evals/conformal.py`) are kept but marked `held_back` —
reviewers see them, patients never do.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from rapidfuzz import fuzz

from pipeline.ir import ClaimIR
from pipeline.m3_extract.grounding import best_match
from pipeline.m4_audit.agents import Proposal
from schemas.claim import DocumentRecord
from schemas.common import Evidence, Severity
from schemas.findings import Finding, FindingOrigin, FindingType, ProofQuote

CALIBRATION_PATH = Path(__file__).parent / "calibration.json"
DEFAULT_THRESHOLD = 0.6
QUOTE_MATCH = 90.0   # partial_ratio needed for a quote to count as present in its document
_LOCATE_WORDS = 8    # quotes are located on the page by their opening words

AGENT_LABEL = {
    "billing": "Billing agent", "clinical_record": "Clinical-record agent",
    "pharmacy": "Pharmacy agent", "timeline": "Timeline agent", "identity": "Identity agent",
}


def load_threshold(path: Path = CALIBRATION_PATH) -> float:
    try:
        return float(json.loads(path.read_text(encoding="utf-8"))["threshold"])
    except (OSError, KeyError, ValueError, TypeError):
        return DEFAULT_THRESHOLD


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def _doc_texts(claim_ir: ClaimIR, records: list[DocumentRecord]) -> dict[str, str]:
    by_page = {p.page: p for p in claim_ir.pages}
    return {r.document_id: _norm(" ".join(by_page[p].text for p in r.page_range
                                          if p in by_page))
            for r in records}


def _ground_quote(quote: dict, records_by_id, texts, claim_ir) -> ProofQuote:
    doc_id = str(quote.get("document_id", ""))
    text = str(quote.get("quote", "")).strip()
    pq = ProofQuote(document_id=doc_id, quote=text)
    if doc_id not in texts or not text:
        return pq
    if fuzz.partial_ratio(_norm(text), texts[doc_id]) < QUOTE_MATCH:
        return pq
    pq.grounded = True
    by_page = {p.page: p for p in claim_ir.pages}
    pages = [by_page[p] for p in records_by_id[doc_id].page_range if p in by_page]
    m = best_match(" ".join(text.split()[:_LOCATE_WORDS]), pages)
    if m and m[0] >= 80:
        pq.evidence = [Evidence(page=m[1], bbox=m[2], ocr_confidence=round(m[3], 4))]
    return pq


def _date(s: str) -> date | None:
    try:
        return date.fromisoformat(str(s).strip()[:10])
    except ValueError:
        return None


def _num(s: str) -> float | None:
    m = re.search(r"-?\d+(?:\.\d+)?", str(s).replace(",", ""))
    return float(m.group()) if m else None


def code_check(p: Proposal, texts: dict[str, str]) -> bool | None:
    """True = the stated problem is confirmed in code; False = refuted; None = nothing to check."""
    v = p.check_values
    if p.check_kind == "date_mismatch" and len(v) >= 2:
        a, b = _date(v[0]), _date(v[1])
        return None if a is None or b is None else a != b
    if p.check_kind == "date_outside_window" and len(v) >= 3:
        d, lo, hi = _date(v[0]), _date(v[1]), _date(v[2])
        return None if None in (d, lo, hi) else (d < lo or d > hi)
    if p.check_kind == "count_mismatch" and len(v) >= 2:
        a, b = _num(v[0]), _num(v[1])
        return None if a is None or b is None else a != b
    if p.check_kind == "missing_document" and v:
        keyword = _norm(v[0])
        cited = {q.get("document_id") for q in p.quotes}
        others = [t for doc_id, t in texts.items() if doc_id not in cited]
        return bool(keyword) and not any(keyword in t for t in others)
    return None


def score(grounded: bool, checked: bool | None, upheld: bool | None) -> float:
    """Verifier score in [0,1]: grounding gates everything; code check and skeptic weigh
    equally; an absent check or skeptic counts as neutral (0.5)."""
    if not grounded:
        return 0.0
    det = 0.5 if checked is None else (1.0 if checked else 0.0)
    sk = 0.5 if upheld is None else (1.0 if upheld else 0.0)
    return round(0.1 + 0.45 * det + 0.45 * sk, 4)


def _same_issue(a: Finding, b: Finding) -> bool:
    return a.type == b.type and bool(set(a.document_ids) & set(b.document_ids))


def verify(
    proposals: list[Proposal],
    claim_ir: ClaimIR,
    records: list[DocumentRecord],
    rule_findings: list[Finding],
    *,
    threshold: float | None = None,
    skeptic_ran: bool = True,
) -> list[Finding]:
    """Turn proposals into findings (numbered after `rule_findings`). Proposals that repeat a
    rule finding are folded into it as corroboration instead of being listed twice."""
    threshold = load_threshold() if threshold is None else threshold
    records_by_id = {r.document_id: r for r in records}
    texts = _doc_texts(claim_ir, records)
    out: list[Finding] = []
    next_id = len(rule_findings) + 1

    for p in proposals:
        label = AGENT_LABEL.get(p.agent, p.agent)
        proof = [_ground_quote(q, records_by_id, texts, claim_ir) for q in p.quotes]
        grounded = bool(proof) and all(q.grounded for q in proof)
        checked = code_check(p, texts) if grounded else None
        upheld = p.skeptic["upheld"] if (p.skeptic and skeptic_ran) else None
        s = score(grounded, checked, upheld)

        trail = [f"Proposed by the {label.lower()}."]
        for q in proof:
            where = f"page {q.evidence[0].page + 1}" if q.evidence else "its text"
            trail.append(f"Quote {'found' if q.grounded else 'NOT found'} in "
                         f"{q.document_id} ({where}): “{q.quote}”.")
        if checked is not None:
            trail.append(f"Code check ({p.check_kind}: {', '.join(p.check_values)}): "
                         f"{'confirmed' if checked else 'refuted'}.")
        if p.skeptic:
            trail.append(f"Skeptic agent: {'upheld' if p.skeptic['upheld'] else 'not upheld'}"
                         f" — {p.skeptic['reason']}")
        held = s < threshold
        trail.append(f"Verifier score {s:.2f} {'<' if held else '≥'} threshold "
                     f"{threshold:.2f}: {'held back' if held else 'shown'}.")

        verified_by = (["grounding"] if grounded else []) + \
            (["code check"] if checked else []) + \
            (["skeptic agent"] if upheld else [])
        try:
            ftype = FindingType(p.type)
            sev = Severity(p.severity)
        except ValueError:
            continue
        doc_ids = list(dict.fromkeys(q.document_id for q in proof if q.document_id
                                     in records_by_id))
        finding = Finding(
            id="", type=ftype, severity=sev, title=p.title, detail=p.detail,
            evidence=[e for q in proof for e in q.evidence], document_ids=doc_ids,
            origin=FindingOrigin.agent, agent=label, proof=proof, verified_by=verified_by,
            verifier_score=s, held_back=held, trail=trail,
        )

        dup_rule = next((r for r in rule_findings if _same_issue(r, finding)), None)
        if dup_rule is not None and not held:
            tag = f"{label} (agreed)"
            if tag not in dup_rule.verified_by:
                dup_rule.verified_by.append(tag)
            continue
        dup = next((f for f in out if _same_issue(f, finding)), None)
        if dup is not None:
            if finding.verifier_score > (dup.verifier_score or 0):
                finding.id = dup.id
                finding.trail.insert(0, f"Also proposed by the {dup.agent.lower()}.")
                out[out.index(dup)] = finding
            elif f"Also proposed by the {label.lower()}." not in dup.trail:
                dup.trail.insert(0, f"Also proposed by the {label.lower()}.")
            continue
        finding.id = f"F-{next_id:03d}"
        next_id += 1
        out.append(finding)
    return out
