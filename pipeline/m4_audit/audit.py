"""M4 — Cross-Document Audit Engine (plan §M4).

Runs a config-driven rule pack (`rules.yaml`) over the extracted documents of a claim and
emits severity-scored **review items** (`Finding`). Each rule's metadata (finding type,
severity, reviewer title, params) lives in YAML; its detection logic is a registered function
here. Every finding links its bbox evidence so a human can judge it — that is what keeps a
finding a review item, never an accusation (CLAUDE.md framing: no "fraud"/"reject").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from rapidfuzz import fuzz

from schemas.claim import DocumentRecord
from schemas.common import DocType, Evidence, Severity
from schemas.findings import Finding, FindingType

_RULES_PATH = Path(__file__).parent / "rules.yaml"


@dataclass
class RuleHit:
    """One firing of a rule: what to review, on which documents, with what evidence."""

    detail: str
    document_ids: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)


_DETECTORS: dict[str, callable] = {}


def rule(rule_id: str):
    def deco(fn):
        _DETECTORS[rule_id] = fn
        return fn
    return deco


def load_rules(path: str | Path | None = None) -> dict:
    return yaml.safe_load(Path(path or _RULES_PATH).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- helpers

def _first(docs: list[DocumentRecord], doc_type: DocType) -> DocumentRecord | None:
    for d in docs:
        if d.extracted is not None and d.extracted.doc_type == doc_type:
            return d
    return None


def _all(docs: list[DocumentRecord], doc_type: DocType) -> list[DocumentRecord]:
    return [d for d in docs if d.extracted is not None and d.extracted.doc_type == doc_type]


def _patient_name_field(extracted):
    if hasattr(extracted, "patient_name"):
        return extracted.patient_name
    if hasattr(extracted, "patient"):
        return extracted.patient.name
    return None


# --------------------------------------------------------------------------- rules

@rule("name_inconsistent")
def _name_inconsistent(docs, params):
    threshold = params.get("threshold", 85)
    entries = []
    for d in docs:
        f = _patient_name_field(d.extracted) if d.extracted else None
        if f is not None and f.value:
            entries.append((d.document_id, f.value, f))
    if len(entries) < 2:
        return []
    from collections import Counter
    canonical = Counter(n for _, n, _ in entries).most_common(1)[0][0]
    hits = []
    for doc_id, name, f in entries:
        if fuzz.token_sort_ratio(name.lower(), canonical.lower()) < threshold:
            hits.append(RuleHit(
                detail=f"Patient name '{name}' does not match '{canonical}' used on other "
                       f"documents; requires review.",
                document_ids=[doc_id], evidence=list(f.evidence)))
    return hits


@rule("date_inconsistent")
def _date_inconsistent(docs, params):
    bill, disch = _first(docs, DocType.hospital_bill), _first(docs, DocType.discharge_summary)
    if not bill or not disch:
        return []
    hits = []
    for attr in ("admission_date", "discharge_date"):
        bf, sf = getattr(bill.extracted, attr), getattr(disch.extracted, attr)
        if bf.value and sf.value and bf.value != sf.value:
            hits.append(RuleHit(
                detail=f"{attr.replace('_', ' ').title()} differs: bill {bf.value} vs "
                       f"discharge summary {sf.value}; requires review.",
                document_ids=[bill.document_id, disch.document_id],
                evidence=[*bf.evidence, *sf.evidence]))
    return hits


@rule("bill_arithmetic_mismatch")
def _bill_arithmetic(docs, params):
    bill = _first(docs, DocType.hospital_bill)
    if not bill:
        return []
    b = bill.extracted
    vals = [b.subtotal.value, b.discount.value, b.tax.value, b.total.value]
    if any(v is None for v in vals):
        return []
    expected = round(b.subtotal.value - b.discount.value + b.tax.value, 2)
    if abs(expected - b.total.value) > 0.01:
        return [RuleHit(
            detail=f"Stated total {b.total.value} does not equal subtotal - discount + tax "
                   f"({expected}); requires review.",
            document_ids=[bill.document_id], evidence=list(b.total.evidence))]
    return []


@rule("inflated_line_item")
def _inflated(docs, params):
    bill = _first(docs, DocType.hospital_bill)
    if not bill:
        return []
    hits = []
    for li in bill.extracted.line_items:
        q, u, a = li.quantity.value, li.unit_price.value, li.amount.value
        if None in (q, u, a):
            continue
        if abs(round(q * u, 2) - a) > 0.01:
            hits.append(RuleHit(
                detail=f"Line '{li.description.value}' amount {a} exceeds quantity x unit "
                       f"price ({round(q * u, 2)}); requires review.",
                document_ids=[bill.document_id], evidence=list(li.amount.evidence)))
    return hits


@rule("duplicate_line_item")
def _duplicate(docs, params):
    bill = _first(docs, DocType.hospital_bill)
    if not bill:
        return []
    seen, hits = set(), []
    for li in bill.extracted.line_items:
        key = (li.description.value, li.amount.value)
        if key in seen:
            hits.append(RuleHit(
                detail=f"Line '{li.description.value}' ({li.amount.value}) appears more than "
                       f"once; requires review.",
                document_ids=[bill.document_id], evidence=list(li.amount.evidence)))
        seen.add(key)
    return hits


@rule("missing_lab_report")
def _missing_lab(docs, params):
    bill = _first(docs, DocType.hospital_bill)
    if not bill or _all(docs, DocType.lab_report):
        return []
    inv = [li for li in bill.extracted.line_items
           if (li.category.value == "investigation"
               or "investigation" in (li.description.value or "").lower())]
    if not inv:
        return []
    return [RuleHit(
        detail="Bill includes investigation charges but no lab report is present in the "
               "file; requires review.",
        document_ids=[bill.document_id], evidence=list(inv[0].amount.evidence))]


@rule("drug_diagnosis_implausible")
def _drug_diagnosis(docs, params):
    markers = params.get("markers", {})
    pharm, disch = _first(docs, DocType.pharmacy_bill), _first(docs, DocType.discharge_summary)
    if not pharm:
        return []
    icds = [c.value for c in disch.extracted.icd10_codes if c.value] if disch else []
    hits = []
    for li in pharm.extracted.line_items:
        name = (li.drug_name.value or "").lower()
        for marker, prefix in markers.items():
            if marker in name and not any((c or "").startswith(prefix) for c in icds):
                doc_ids = [pharm.document_id] + ([disch.document_id] if disch else [])
                hits.append(RuleHit(
                    detail=f"'{li.drug_name.value}' billed but the recorded diagnosis codes "
                           f"{icds or '[]'} do not support it; requires review.",
                    document_ids=doc_ids, evidence=list(li.drug_name.evidence)))
    return hits


@rule("non_payable_consumable")
def _non_payable(docs, params):
    keywords = [k.lower() for k in params.get("keywords", [])]
    bill = _first(docs, DocType.hospital_bill)
    if not bill:
        return []
    hits = []
    for li in bill.extracted.line_items:
        desc = (li.description.value or "").lower()
        if any(k in desc for k in keywords):
            hits.append(RuleHit(
                detail=f"'{li.description.value}' is a standard non-payable consumable; "
                       f"confirm it is excluded from the claim.",
                document_ids=[bill.document_id], evidence=list(li.amount.evidence)))
    return hits


# --------------------------------------------------------------------------- engine

def run_audit(docs: list[DocumentRecord], config: dict | None = None) -> list[Finding]:
    """Run the enabled rule pack over a claim's documents and return review items."""
    cfg = config or load_rules()
    findings: list[Finding] = []
    for spec in cfg.get("rules", []):
        if not spec.get("enabled", True):
            continue
        detector = _DETECTORS.get(spec["id"])
        if detector is None:
            continue
        for hit in detector(docs, spec.get("params", {})):
            findings.append(Finding(
                id=f"F-{len(findings) + 1:03d}",
                type=FindingType(spec["type"]),
                severity=Severity(spec["severity"]),
                title=spec["title"],
                detail=hit.detail,
                evidence=hit.evidence,
                document_ids=hit.document_ids,
                rule_id=spec["id"],
            ))
    return findings
