"""Fault injection for MediClaim-Bench (plan §5).

A *clean* claim from `sample_claim` has zero faults. This module seeds one problem into a
claim and records a `FaultLabel` (with the `FindingType` the audit engine is expected to
raise), so the eval harness can score audit precision/recall per fault type (plan §7).

Design rules that keep the benchmark honest:
  * Each fault is **isolated** — it triggers exactly one finding type. Where a fault could
    incidentally break bill arithmetic, we recompute the totals so only the intended check
    fires (e.g. an inflated *line* breaks `amount == qty x unit_price` but the claim total
    still reconciles, so it is not also a `bill_arithmetic_mismatch`).
  * Injection uses the same curated tables the audit reads (see
    `fake_data.SPECIALTY_MARKER_DRUGS`) so injection and detection can never drift.
  * Deterministic: the same (claim, seed) always injects the same fault (CLAUDE.md rule 6).

Language stays review-item, never accusatory (CLAUDE.md framing).
"""

from __future__ import annotations

import random
from datetime import timedelta

from datagen import fake_data as fd
from schemas.common import Severity
from schemas.ground_truth import (
    FAULT_TO_FINDING,
    BillLineItem,
    ClaimGroundTruth,
    DischargeSummaryGT,
    FaultLabel,
    FaultType,
    HospitalBillGT,
    LabReportGT,
    PharmacyBillGT,
    PharmacyLineItem,
)

_SEVERITY: dict[FaultType, Severity] = {
    FaultType.inflated_line_item: Severity.critical,
    FaultType.bill_arithmetic_error: Severity.warning,
    FaultType.duplicate_billing: Severity.warning,
    FaultType.date_mismatch: Severity.warning,
    FaultType.name_mismatch: Severity.warning,
    FaultType.missing_lab_report: Severity.warning,
    FaultType.drug_diagnosis_mismatch: Severity.critical,
}


def _first(claim: ClaimGroundTruth, model):
    for d in claim.documents:
        if isinstance(d, model):
            return d
    return None


def _reconcile_bill(bill: HospitalBillGT) -> None:
    """Recompute subtotal/tax/total from line amounts so claim-level arithmetic stays exact.

    Used after a line-level fault so the *only* thing wrong is the line, not the totals.
    """
    bill.subtotal = fd.money(sum(i.amount for i in bill.line_items))
    bill.tax = fd.money((bill.subtotal - bill.discount) * 0.05)
    bill.total = fd.money(bill.subtotal - bill.discount + bill.tax)


def _label(fault: FaultType, detail: str, doc_ids: list[str]) -> FaultLabel:
    return FaultLabel(
        fault_type=fault,
        severity=_SEVERITY[fault],
        description=detail,
        document_ids=doc_ids,
        expected_finding=FAULT_TO_FINDING[fault],
    )


# --------------------------------------------------------------------- fault recipes
# Each returns a FaultLabel if it could apply to this claim, else None.


def _inflate_line_item(claim, rng) -> FaultLabel | None:
    bill = _first(claim, HospitalBillGT)
    if bill is None or not bill.line_items:
        return None
    # Pick a substantial line (procedure/room), inflate its stated amount ~5x while leaving
    # unit_price x quantity untouched -> line math breaks, totals still reconcile.
    idx = max(range(len(bill.line_items)), key=lambda i: bill.line_items[i].amount)
    item = bill.line_items[idx]
    item.amount = fd.money(item.amount * 5)
    _reconcile_bill(bill)
    return _label(
        FaultType.inflated_line_item,
        f"Billed amount for '{item.description}' is far above quantity x unit price.",
        [bill.document_id],
    )


def _bill_arithmetic_error(claim, rng) -> FaultLabel | None:
    bill = _first(claim, HospitalBillGT)
    if bill is None:
        return None
    # Tamper the stated total only; every line stays internally exact.
    bill.total = fd.money(bill.total + rng.choice([2500.0, 5000.0, 7500.0]))
    return _label(
        FaultType.bill_arithmetic_error,
        "Stated bill total does not equal subtotal - discount + tax.",
        [bill.document_id],
    )


def _duplicate_billing(claim, rng) -> FaultLabel | None:
    bill = _first(claim, HospitalBillGT)
    if bill is None or not bill.line_items:
        return None
    src = max(bill.line_items, key=lambda i: i.amount)
    dup = BillLineItem(**src.model_dump())
    bill.line_items.append(dup)
    _reconcile_bill(bill)
    return _label(
        FaultType.duplicate_billing,
        f"Line item '{src.description}' appears more than once on the bill.",
        [bill.document_id],
    )


def _date_mismatch(claim, rng) -> FaultLabel | None:
    bill = _first(claim, HospitalBillGT)
    disch = _first(claim, DischargeSummaryGT)
    if bill is None or disch is None:
        return None
    bill.discharge_date = disch.discharge_date + timedelta(days=rng.randint(2, 5))
    return _label(
        FaultType.date_mismatch,
        "Discharge date on the bill does not match the discharge summary.",
        [bill.document_id, disch.document_id],
    )


def _name_mismatch(claim, rng) -> FaultLabel | None:
    pharm = _first(claim, PharmacyBillGT)
    if pharm is None:
        return None
    parts = pharm.patient_name.split()
    # Alter the surname so cross-document name matching flags it.
    parts[-1] = rng.choice(["Kumar", "Sharma", "Nair", "Das", "Patel"])
    pharm.patient_name = " ".join(parts)
    return _label(
        FaultType.name_mismatch,
        "Patient name on the pharmacy bill differs from the rest of the claim.",
        [pharm.document_id],
    )


def _missing_lab_report(claim, rng) -> FaultLabel | None:
    labs = [d for d in claim.documents if isinstance(d, LabReportGT)]
    bill = _first(claim, HospitalBillGT)
    if not labs or bill is None:
        return None
    removed_ids = [d.document_id for d in labs]
    claim.documents = [d for d in claim.documents if not isinstance(d, LabReportGT)]
    # Remove lab_report template metadata too, so completeness/segmentation see no labs.
    claim.template_meta.pop("lab_report", None)
    return _label(
        FaultType.missing_lab_report,
        "Bill includes investigation charges but no lab report is present in the file.",
        removed_ids,
    )


def _drug_diagnosis_mismatch(claim, rng) -> FaultLabel | None:
    pharm = _first(claim, PharmacyBillGT)
    disch = _first(claim, DischargeSummaryGT)
    if pharm is None or disch is None:
        return None
    icd = disch.icd10_codes
    for key, prefix in fd.SPECIALTY_MARKER_DRUGS.items():
        justified = any(code.startswith(prefix) for code in icd)
        already = any(key.split()[0].lower() in ln.drug_name.lower() for ln in pharm.line_items)
        if not justified and not already:
            drug = fd.DRUGS[key]
            pharm.line_items.append(PharmacyLineItem(
                drug_name=f"{drug.name} {drug.strength}",
                batch_no=f"B{rng.randint(10000, 99999)}",
                quantity=1, mrp=drug.unit_mrp, amount=fd.money(drug.unit_mrp),
            ))
            pharm.total = fd.money(sum(ln.amount for ln in pharm.line_items))
            return _label(
                FaultType.drug_diagnosis_mismatch,
                f"'{drug.name}' billed but the recorded diagnosis does not support it.",
                [pharm.document_id, disch.document_id],
            )
    return None


# Try order is shuffled per seed; the first recipe that applies wins.
_RECIPES = {
    FaultType.inflated_line_item: _inflate_line_item,
    FaultType.bill_arithmetic_error: _bill_arithmetic_error,
    FaultType.duplicate_billing: _duplicate_billing,
    FaultType.date_mismatch: _date_mismatch,
    FaultType.name_mismatch: _name_mismatch,
    FaultType.missing_lab_report: _missing_lab_report,
    FaultType.drug_diagnosis_mismatch: _drug_diagnosis_mismatch,
}


def inject_fault(
    claim: ClaimGroundTruth, seed: int, fault_type: FaultType | None = None
) -> ClaimGroundTruth:
    """Seed one fault into `claim` (mutated in place) and record its `FaultLabel`.

    `fault_type=None` picks one deterministically from `seed`. If a requested/selected fault
    cannot apply to this claim, the recipes are tried in a seeded order until one does.
    Returns the same claim object for convenience.
    """
    rng = random.Random(seed * 7 + 13)
    if fault_type is not None:
        order = [fault_type] + [f for f in _RECIPES if f != fault_type]
    else:
        order = list(_RECIPES)
        rng.shuffle(order)

    for ft in order:
        label = _RECIPES[ft](claim, rng)
        if label is not None:
            claim.faults.append(label)
            return claim
    return claim  # nothing applicable (shouldn't happen for a standard claim)


def maybe_inject_fault(
    claim: ClaimGroundTruth, seed: int, rate: float = 0.1
) -> ClaimGroundTruth:
    """Inject a fault into ~`rate` of claims, chosen deterministically by seed (plan §5)."""
    if random.Random(seed * 31 + 5).random() < rate:
        inject_fault(claim, seed)
    return claim
