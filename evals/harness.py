"""Eval harness (plan §7): run the pipeline over a synthetic set and score it vs ground truth.

Produces the numbers `make eval` writes into the README:
  * segmentation/classification accuracy
  * field-extraction exact- and normalized-match accuracy (overall + per doc type)
  * audit recall per fault type + false-positive rate on clean files
  * a coverage–accuracy curve (accuracy of auto-accepted fields vs % sent to review)
  * hybrid unit economics (how much the deterministic layer saves vs pure-LLM)

Everything is seed-driven and rendered on the fly, so the numbers reproduce exactly.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from datagen import inject_fault, sample_claim
from datagen.render import render_claim
from pipeline import run_pipeline
from pipeline.m3_extract.grounding import _walk_fields
from schemas.ground_truth import (
    FAULT_TO_FINDING,
    ClaimGroundTruth,
    DischargeSummaryGT,
    FaultType,
    HospitalBillGT,
    LabReportGT,
    PharmacyBillGT,
    PrescriptionGT,
)

# The eval doc types (claim_form/id are not modelled yet).
_TYPES = ["hospital_bill", "discharge_summary", "pharmacy_bill", "lab_report", "prescription"]


def _norm(v):
    if isinstance(v, str):
        return v.strip().lower()
    if isinstance(v, float):
        return round(v, 2)
    return v


def _pair_documents(gt: ClaimGroundTruth, claim_file):
    """Pair each ground-truth document with its extracted counterpart, matched by type in
    order (a claim can hold several docs of one type, e.g. multiple lab reports)."""
    from collections import defaultdict
    ext_lists: dict[str, list] = defaultdict(list)
    for d in claim_file.documents:
        if d.extracted is not None:
            ext_lists[d.doc_type.value].append(d.extracted)
    cursor: dict[str, int] = defaultdict(int)
    pairs = []
    for gt_doc in gt.documents:
        t = gt_doc.doc_type.value
        lst = ext_lists.get(t, [])
        i = cursor[t]
        cursor[t] += 1
        pairs.append((gt_doc, lst[i] if i < len(lst) else None))
    return pairs


def _pairs(gt_doc, ext) -> list[tuple[str, object, object]]:
    """(field_id, ground_truth_value, extracted_value) for one document."""
    out: list[tuple[str, object, object]] = []

    def add(fid, gv, field_obj):
        out.append((fid, gv, field_obj.value if field_obj is not None else None))

    if isinstance(gt_doc, HospitalBillGT):
        add("patient.name", gt_doc.patient.name, ext.patient.name)
        add("patient.age", gt_doc.patient.age, ext.patient.age)
        add("admission_date", gt_doc.admission_date, ext.admission_date)
        add("discharge_date", gt_doc.discharge_date, ext.discharge_date)
        add("total", gt_doc.total, ext.total)
        add("subtotal", gt_doc.subtotal, ext.subtotal)
        for i, gli in enumerate(gt_doc.line_items):
            if i < len(ext.line_items):
                add(f"line_items.{i}.amount", gli.amount, ext.line_items[i].amount)
    elif isinstance(gt_doc, DischargeSummaryGT):
        add("patient.name", gt_doc.patient.name, ext.patient.name)
        add("diagnosis_text", gt_doc.diagnosis_text, ext.diagnosis_text)
        add("treating_doctor", gt_doc.treating_doctor, ext.treating_doctor)
        gt_icd = gt_doc.icd10_codes[0] if gt_doc.icd10_codes else None
        ext_icd = ext.icd10_codes[0] if ext.icd10_codes else None
        add("icd10", gt_icd, ext_icd)
    elif isinstance(gt_doc, PharmacyBillGT):
        add("patient_name", gt_doc.patient_name, ext.patient_name)
        add("total", gt_doc.total, ext.total)
        for i, gli in enumerate(gt_doc.line_items):
            if i < len(ext.line_items):
                add(f"line_items.{i}.drug_name", gli.drug_name, ext.line_items[i].drug_name)
    elif isinstance(gt_doc, PrescriptionGT):
        add("patient.name", gt_doc.patient.name, ext.patient.name)
        add("doctor", gt_doc.doctor, ext.doctor)
        for i, gmed in enumerate(gt_doc.medications):
            if i < len(ext.medications):
                add(f"medications.{i}", gmed.drug_name, ext.medications[i])
    elif isinstance(gt_doc, LabReportGT):
        add("patient.name", gt_doc.patient.name, ext.patient.name)
        add("panel_name", gt_doc.panel_name, ext.panel_name)
    return out


@dataclass
class Report:
    n_claims: int = 0
    n_clean: int = 0
    n_faulty: int = 0
    classification_correct: int = 0
    classification_total: int = 0
    exact_by_type: dict = field(default_factory=dict)     # type -> [correct, total]
    norm_by_type: dict = field(default_factory=dict)
    fault_recall: dict = field(default_factory=dict)      # fault -> [caught, total]
    clean_false_positives: int = 0
    coverage_points: list = field(default_factory=list)   # (confidence, correct)
    source_counts: dict = field(default_factory=dict)     # source -> n
    latencies: list = field(default_factory=list)

    def _rate(self, pair):
        c, t = pair
        return c / t if t else 0.0


def _score_claim(report: Report, gt: ClaimGroundTruth, claim_file, faulty: bool) -> None:
    pairs = _pair_documents(gt, claim_file)

    # classification: each GT doc's type should appear among the segmented docs
    seg_types = [d.doc_type.value for d in claim_file.documents]
    for gt_doc in gt.documents:
        report.classification_total += 1
        if gt_doc.doc_type.value in seg_types:
            report.classification_correct += 1

    # extraction fidelity + coverage-accuracy (GT paired with its own extracted document)
    for gt_doc, ext in pairs:
        if ext is None:
            continue
        t = gt_doc.doc_type.value
        report.exact_by_type.setdefault(t, [0, 0])
        report.norm_by_type.setdefault(t, [0, 0])
        for fid, gv, ev in _pairs(gt_doc, ext):
            report.exact_by_type[t][1] += 1
            report.norm_by_type[t][1] += 1
            if gv == ev:
                report.exact_by_type[t][0] += 1
            if _norm(gv) == _norm(ev):
                report.norm_by_type[t][0] += 1
            if ev is not None:
                report.coverage_points.append((_confidence_of(ext, fid), _norm(gv) == _norm(ev)))

    # audit: recall on faulty claims, false positives on clean claims
    severe = [f for f in claim_file.findings if f.severity.value in ("warning", "critical")]
    if faulty:
        for fault in gt.faults:
            report.fault_recall.setdefault(fault.fault_type.value, [0, 0])
            report.fault_recall[fault.fault_type.value][1] += 1
            expected = FAULT_TO_FINDING[fault.fault_type].value
            if any(f.type.value == expected for f in claim_file.findings):
                report.fault_recall[fault.fault_type.value][0] += 1
    else:
        report.clean_false_positives += len(severe)

    # source mix over every extracted field in the claim
    for doc in claim_file.documents:
        if doc.extracted is None:
            continue
        for f in _walk_fields(doc.extracted):
            report.source_counts[f.source.value] = report.source_counts.get(f.source.value, 0) + 1


def _confidence_of(ext, field_id: str) -> float:
    obj = ext
    for part in field_id.split("."):
        obj = obj[int(part)] if part.isdigit() else getattr(obj, part, None)
        if obj is None:
            return 0.0
    return getattr(obj, "confidence", 0.0)


def build_and_score(seeds_clean: list[int], seeds_faulty: dict[int, str], out_dir: Path) -> Report:
    """Render each claim, run the pipeline, and accumulate metrics vs ground truth."""
    out_dir = Path(out_dir)
    report = Report()
    plan: list[tuple[int, str | None]] = [(s, None) for s in seeds_clean]
    plan += [(s, fault) for s, fault in seeds_faulty.items()]

    for seed, fault in plan:
        claim = sample_claim(seed=seed)
        if fault:
            inject_fault(claim, seed=seed, fault_type=FaultType(fault))
        cdir = out_dir / claim.claim_id
        render_claim(claim, cdir)

        t0 = time.perf_counter()
        result = run_pipeline(cdir / "claim.pdf", claim_id=claim.claim_id)
        report.latencies.append(time.perf_counter() - t0)

        report.n_claims += 1
        faulty = not claim.is_clean
        report.n_faulty += faulty
        report.n_clean += not faulty
        _score_claim(report, claim, result, faulty)
    return report


def coverage_accuracy_curve(points: list[tuple[float, bool]], steps=(0.0, 0.1, 0.2, 0.3)):
    """For each 'route the lowest-confidence X% to review', the accuracy of what's auto-accepted."""
    if not points:
        return []
    ordered = sorted(points, key=lambda p: p[0], reverse=True)  # high confidence first
    n = len(ordered)
    curve = []
    for reviewed in steps:
        keep = ordered[: max(1, int(round(n * (1 - reviewed))))]
        acc = sum(c for _, c in keep) / len(keep)
        curve.append((reviewed, len(keep) / n, acc))
    return curve
