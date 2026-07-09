"""M3 — LLM fallback + confidence fusion (plan §M3).

Hybrid routing: the deterministic layer runs first; the LLM is asked **only** for fields it
left empty or below the amber threshold. Each LLM value gets a self-consistency confidence
(k=3 samples), then is fused with any rule value:

  * rule & LLM agree      -> max(conf) + 0.05
  * rule & LLM conflict   -> 0.25 and auto-flag for HITL

All LLM traffic goes through `LLMClient` (record/replay). A missing fixture or a malformed
reply degrades gracefully to `value=None, confidence=0` — the pipeline never crashes.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from datetime import date, datetime

from pipeline.m3_extract.confidence import (
    CONFLICT_CONFIDENCE,
    LLM_AGREE_FULL,
    LLM_AGREE_NONE,
    LLM_AGREE_PARTIAL,
    VALIDATOR_BONUS,
    missing_field,
)
from pipeline.m3_extract.llm_client import LLMClient, MissingFixture
from schemas.common import AMBER_THRESHOLD, DocType, ExtractedField, FieldSource

Parser = Callable[[str], object | None]


# --------------------------------------------------------------------------- parsers

def parse_str(s: str) -> str | None:
    return s.strip() or None


def parse_date(s: str) -> date | None:
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%d %b %Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_float(s: str) -> float | None:
    try:
        return round(float(str(s).replace(",", "").strip()), 2)
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------- fusion

def llm_confidence(n_agree: int, k: int = 3, validated: bool | None = None) -> float:
    """Self-consistency score (plan §M3): 3/3→0.85, 2/3→0.60, else 0.30; ±validator."""
    if n_agree >= 3:
        base = LLM_AGREE_FULL
    elif n_agree == 2:
        base = LLM_AGREE_PARTIAL
    else:
        base = LLM_AGREE_NONE
    if validated is True:
        base = min(1.0, base + VALIDATOR_BONUS)
    elif validated is False:
        base = min(base, 0.30)  # a failed validator forces low confidence
    return round(base, 4)


def _equal(a, b) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return a.strip().lower() == b.strip().lower()
    return a == b


def fuse_field(rule: ExtractedField | None, llm: ExtractedField | None) -> ExtractedField:
    """Combine a rule value and an LLM value per plan §M3's fusion rules."""
    if llm is None or llm.value is None:
        return rule if rule is not None else missing_field()
    if rule is None or rule.value is None:
        return llm
    if _equal(rule.value, llm.value):
        conf = min(1.0, max(rule.confidence, llm.confidence) + 0.05)
        return ExtractedField(value=rule.value, confidence=round(conf, 4),
                              source=FieldSource.fusion, evidence=rule.evidence, flags=rule.flags)
    return ExtractedField(value=rule.value, confidence=CONFLICT_CONFIDENCE,
                          source=FieldSource.fusion, evidence=rule.evidence,
                          flags=[*rule.flags, "rule_llm_conflict"])


# --------------------------------------------------------------- LLM field filling

def fill_field(
    client: LLMClient, key: str, parser: Parser, validate: Callable | None = None
) -> ExtractedField:
    """Ask the LLM (via record/replay) for one field; degrade to null on any failure."""
    try:
        resp = client.complete("", key=key)
        samples = json.loads(resp.text).get("samples", [])
    except (MissingFixture, json.JSONDecodeError, TypeError, KeyError):
        return missing_field()  # no fixture / malformed reply -> pipeline never crashes
    parsed = [p for s in samples if (p := parser(str(s))) is not None]
    if not parsed:
        return missing_field()
    modal, n_agree = Counter(map(_hashable, parsed)).most_common(1)[0]
    value = next(p for p in parsed if _hashable(p) == modal)
    validated = validate(value) if validate else None
    return ExtractedField(value=value, confidence=llm_confidence(n_agree, len(samples), validated),
                          source=FieldSource.llm)


def _hashable(v):
    return v.isoformat() if isinstance(v, date) else v


# --------------------------------------------------- hybrid routing over a document

def _get(doc, path: str) -> ExtractedField | None:
    obj = doc
    for part in path.split("."):
        obj = getattr(obj, part, None)
        if obj is None:
            return None
    return obj


def _set(doc, path: str, field: ExtractedField) -> None:
    obj = doc
    parts = path.split(".")
    for part in parts[:-1]:
        obj = getattr(obj, part)
    setattr(obj, parts[-1], field)


def _fallback_key(doc_type: DocType, path: str, context: str) -> str:
    import hashlib
    raw = f"{doc_type.value}:{path}:{context}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


# Scalar fields the LLM fallback may fill, with how to parse them. (Line items are left to
# the deterministic table parser.) The fallback only fires for fields rules left weak.
FILLABLE: dict[DocType, list[tuple[str, Parser]]] = {
    DocType.hospital_bill: [("hospital_name", parse_str), ("patient.name", parse_str),
                            ("admission_date", parse_date), ("discharge_date", parse_date)],
    DocType.discharge_summary: [("diagnosis_text", parse_str), ("treating_doctor", parse_str)],
    DocType.pharmacy_bill: [("pharmacy_name", parse_str), ("patient_name", parse_str)],
    DocType.prescription: [("doctor", parse_str), ("diagnosis_text", parse_str)],
    DocType.lab_report: [("lab_name", parse_str), ("panel_name", parse_str)],
}


def apply_llm_fallback(doc, client: LLMClient, context: str):
    """Fill low-confidence scalar fields via the LLM and fuse with the rule value (in place)."""
    for path, parser in FILLABLE.get(doc.doc_type, []):
        cur = _get(doc, path)
        if cur is not None and cur.value is not None and cur.confidence >= AMBER_THRESHOLD:
            continue  # rules already confident -> LLM never touches it (hybrid routing)
        llm = fill_field(client, _fallback_key(doc.doc_type, path, context), parser)
        _set(doc, path, fuse_field(cur, llm))
    return doc
