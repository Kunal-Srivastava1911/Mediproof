"""The claim's shared timeline and evidence map (the claim evidence graph, within one claim).

Both are built from extracted fields only — no LLM — and then annotated with the findings
that touch them, so the dashboard can show *where* documents disagree:

* **timeline** — every dated event, per document, on one calendar (stays as spans)
* **evidence map** — every shared fact (patient name, admission/discharge dates, treating
  doctor) as each document states it; a cell disagreeing with the row's majority is a
  conflict, and a report a finding says is absent becomes a "missing" cell
"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

from schemas.claim import DocumentRecord, EvidenceCell, TimelineEvent
from schemas.common import DocType
from schemas.findings import Finding, FindingType

_DATE_TYPES = {FindingType.date_inconsistent, FindingType.temporal_inconsistency,
               FindingType.unsupported_by_documentation}


def _v(field):
    return getattr(field, "value", None) if field is not None else None


def build_timeline(records: list[DocumentRecord], findings: list[Finding]) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []

    def add(rec, label, start, end=None):
        if start is not None:
            events.append(TimelineEvent(document_id=rec.document_id, doc_type=rec.doc_type,
                                        label=label, start=start, end=end))

    for rec in records:
        e = rec.extracted
        if e is None:
            continue
        if rec.doc_type == DocType.claim_form:
            add(rec, "Admission", _v(e.admission_date))
            add(rec, "Discharge", _v(e.discharge_date))
        elif rec.doc_type == DocType.hospital_bill:
            admit, disch = _v(e.admission_date), _v(e.discharge_date)
            icu = next((li for li in e.line_items
                        if (_v(li.description) or "").lower().startswith("icu")), None)
            icu_days = int(_v(icu.quantity) or 0) if icu else 0
            if admit and icu_days:
                add(rec, f"ICU · {icu_days} day{'s' if icu_days != 1 else ''} billed", admit,
                    admit + timedelta(days=icu_days - 1))
                add(rec, "Ward", admit + timedelta(days=icu_days), disch)
            else:
                add(rec, "Stay", admit, disch)
        elif rec.doc_type == DocType.discharge_summary:
            add(rec, "Stay", _v(e.admission_date), _v(e.discharge_date))
        elif rec.doc_type == DocType.pharmacy_bill:
            add(rec, "Pharmacy bill", _v(e.bill_date))
        elif rec.doc_type == DocType.lab_report:
            add(rec, _v(e.panel_name) or "Report", _v(e.report_date))
        elif rec.doc_type == DocType.prescription:
            add(rec, "Prescription", _v(e.prescription_date))

    for f in findings:
        if f.held_back or f.type not in _DATE_TYPES:
            continue
        for ev in events:
            if ev.document_id in f.document_ids:
                ev.conflict = True
                ev.finding_ids.append(f.id)
    events.sort(key=lambda ev: (ev.start, ev.document_id))
    return events


def _name(rec: DocumentRecord):
    e = rec.extracted
    if rec.doc_type == DocType.claim_form:
        return _v(e.insured_name)
    if hasattr(e, "patient_name"):
        return _v(e.patient_name)
    if hasattr(e, "patient"):
        return _v(e.patient.name)
    return None


def build_evidence_map(records: list[DocumentRecord], findings: list[Finding]
                       ) -> list[EvidenceCell]:
    facts: dict[str, list[tuple[DocumentRecord, str]]] = {}

    def put(fact, rec, value):
        if value is not None:
            shown = value.strftime("%d %b %Y") if hasattr(value, "strftime") else str(value)
            facts.setdefault(fact, []).append((rec, shown))

    for rec in records:
        e = rec.extracted
        if e is None:
            continue
        put("Patient name", rec, _name(rec))
        if hasattr(e, "admission_date"):
            put("Admission date", rec, _v(e.admission_date))
            put("Discharge date", rec, _v(e.discharge_date))
        if rec.doc_type == DocType.discharge_summary:
            put("Treating doctor", rec, _v(e.treating_doctor))
        if rec.doc_type == DocType.prescription:
            put("Treating doctor", rec, _v(e.doctor))

    shown = [f for f in findings if not f.held_back]
    cells: list[EvidenceCell] = []
    for fact, rows in facts.items():
        majority = Counter(v.strip().lower() for _, v in rows).most_common(1)[0][0]
        for rec, value in rows:
            status = "agrees" if value.strip().lower() == majority else "conflicts"
            ids = [f.id for f in shown if rec.document_id in f.document_ids
                   and status == "conflicts"]
            cells.append(EvidenceCell(fact=fact, document_id=rec.document_id,
                                      doc_type=rec.doc_type, value=value, status=status,
                                      finding_ids=ids))
    for f in shown:
        if f.type in (FindingType.missing_report, FindingType.missing_lab_report):
            cells.append(EvidenceCell(fact=f.title, document_id="(not in file)",
                                      doc_type=DocType.other, value="not in the file",
                                      status="missing", finding_ids=[f.id]))
    return cells
