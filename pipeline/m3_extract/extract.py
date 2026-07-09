"""M3 — Deterministic extraction layer (plan §M3).

Regex + validators over the ingested text layer. On our digital synthetic PDFs this fills
almost every field with high confidence; the LLM fallback (`fuse.py`) only touches what this
leaves empty or low-confidence. Values are grounded to bounding boxes later by M3.5.

The parser is keyed to the datagen templates' stable label/table structure (see
`datagen/templates/`): line 0 is `<Org> <UPPERCASE TITLE>`, info-grid pairs render two per
visual line, and every table row starts with an index and is anchored by an enum/batch token.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from pipeline.ir import ClaimIR
from pipeline.m3_extract.confidence import missing_field, rule_field
from schemas.claim import DocumentRecord
from schemas.common import DocType, ExtractedField, Gender
from schemas.documents import (
    ExtractedBillLine,
    ExtractedDischargeSummary,
    ExtractedDocument,
    ExtractedHospitalBill,
    ExtractedLabReport,
    ExtractedLabResult,
    ExtractedPatient,
    ExtractedPharmacyBill,
    ExtractedPharmacyLine,
    ExtractedPrescription,
)
from schemas.ground_truth import BillCategory

_DOC_TITLES = ("IN-PATIENT BILL", "DISCHARGE SUMMARY", "PHARMACY INVOICE",
               "LAB REPORT", "PRESCRIPTION")
_CATEGORIES = "|".join(c.value for c in BillCategory)
_BILL_ROW = re.compile(
    rf"^\s*\d+\s+(.+?)\s+({_CATEGORIES})\s+(\d+(?:\.\d+)?)\s+(\d+\.\d{{2}})\s+(\d+\.\d{{2}})\s*$"
)
_PHARM_ROW = re.compile(
    r"^\s*\d+\s+(.+?)\s+B\d+\s+(\d+(?:\.\d+)?)\s+(\d+\.\d{2})\s+(\d+\.\d{2})\s*$"
)
_RX_ROW = re.compile(r"^\s*\d+\s+(.+?)\s+\d-\d-\d\s+.+$")
_DATE_RE = r"(\d{2} \w{3} \d{4})"


# --------------------------------------------------------------------------- helpers

def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%d %b %Y").date()
    except ValueError:
        return None


def _search(pattern: str, text: str, group: int = 1) -> str | None:
    m = re.search(pattern, text)
    return m.group(group).strip() if m else None


def _line_amount(lines: list[str], prefix: str) -> float | None:
    for ln in lines:
        if ln.lower().startswith(prefix.lower()):
            nums = re.findall(r"\d+\.\d{2}", ln)
            if nums:
                return float(nums[-1])
    return None


def _org_name(first_line: str) -> str | None:
    name = first_line
    for title in _DOC_TITLES:
        name = re.sub(rf"\s*{re.escape(title)}\s*$", "", name)
    return name.strip() or None


def _patient(text: str) -> ExtractedPatient:
    p = ExtractedPatient()
    name = _search(r"Patient Name (.+?)(?: UHID| Bill No| Age /|$)", text)
    if name:
        p.name = rule_field(name)
    age_m = re.search(r"Age\s*/\s*Sex\s+(\d+)\s*/\s*([MFO])", text)
    if age_m:
        p.age = rule_field(int(age_m.group(1)), validated=True)
        p.gender = rule_field(Gender(age_m.group(2)))
    uhid = _search(r"UHID\s+(UHID\d+)", text)
    if uhid:
        p.patient_id = rule_field(uhid)
    return p


def _date_field(text: str, label: str, *, other: date | None = None) -> ExtractedField:
    d = _parse_date(_search(rf"{label}\s+{_DATE_RE}", text))
    if d is None:
        return missing_field()
    # date-logic validator: admission strictly before discharge (plan §M3)
    validated = other is None or (
        d > other if "Discharge" in label else d < other if "Admission" in label else False
    )
    return rule_field(d, validated=validated)


# --------------------------------------------------------------------- per doc type

def _extract_hospital_bill(text: str, lines: list[str]) -> ExtractedHospitalBill:
    doc = ExtractedHospitalBill()
    doc.hospital_name = rule_field(_org_name(lines[0])) if lines else missing_field()
    doc.patient = _patient(text)
    if (bill_no := _search(r"Bill No (\S+)", text)):
        doc.bill_no = rule_field(bill_no)
    doc.bill_date = ExtractedField()
    if (bd := _parse_date(_search(rf"Date:\s*.*?{_DATE_RE}", text))):
        doc.bill_date = rule_field(bd)
    admit = _parse_date(_search(rf"Admission Date {_DATE_RE}", text))
    disch = _parse_date(_search(rf"Discharge Date {_DATE_RE}", text))
    doc.admission_date = rule_field(admit, validated=bool(admit and disch and admit < disch)) \
        if admit else missing_field()
    doc.discharge_date = rule_field(disch, validated=bool(admit and disch and admit < disch)) \
        if disch else missing_field()

    for ln in lines:
        m = _BILL_ROW.match(ln)
        if not m:
            continue
        desc = re.sub(r"\s*\(non-payable\)\s*", "", m.group(1)).strip()
        line_valid = round(float(m.group(3)) * float(m.group(4)), 2) == float(m.group(5))
        doc.line_items.append(ExtractedBillLine(
            description=rule_field(desc),
            category=rule_field(BillCategory(m.group(2))),
            quantity=rule_field(float(m.group(3))),
            unit_price=rule_field(float(m.group(4))),
            amount=rule_field(float(m.group(5)), validated=line_valid),
        ))

    subtotal = _line_amount(lines, "Subtotal")
    total = _line_amount(lines, "Total Payable")
    reconciles = bool(subtotal and doc.line_items
                      and round(sum(li.amount.value for li in doc.line_items), 2) == subtotal)
    if subtotal is not None:
        doc.subtotal = rule_field(subtotal, validated=reconciles)
    if (disc := _line_amount(lines, "Discount")) is not None:
        doc.discount = rule_field(disc)
    if (tax := _line_amount(lines, "Tax")) is not None:
        doc.tax = rule_field(tax)
    if total is not None:
        doc.total = rule_field(total, validated=reconciles)
    return doc


def _extract_discharge(text: str, lines: list[str]) -> ExtractedDischargeSummary:
    doc = ExtractedDischargeSummary()
    doc.hospital_name = rule_field(_org_name(lines[0])) if lines else missing_field()
    doc.patient = _patient(text)
    admit = _parse_date(_search(rf"Admission Date {_DATE_RE}", text))
    disch = _parse_date(_search(rf"Discharge Date {_DATE_RE}", text))
    if admit:
        doc.admission_date = rule_field(admit, validated=bool(disch and admit < disch))
    if disch:
        doc.discharge_date = rule_field(disch, validated=bool(admit and admit < disch))
    if (doctor := _search(r"Treating Doctor (.+?)(?:\s*\(|$)", text)):
        doc.treating_doctor = rule_field(doctor)
    # diagnosis: the line after the "Final Diagnosis" heading
    for i, ln in enumerate(lines):
        if ln.strip().lower() == "final diagnosis" and i + 1 < len(lines):
            doc.diagnosis_text = rule_field(lines[i + 1].strip())
            break
    if (icd := _search(r"ICD-10:\s*(.+)", text)):
        codes = [c.strip() for c in icd.split(",") if c.strip()]
        valid = re.compile(r"^[A-TV-Z]\d{2}(\.\d{1,2})?$")  # ICD-10 code format validator
        doc.icd10_codes = [rule_field(c, validated=bool(valid.match(c))) for c in codes]
    return doc


def _extract_pharmacy(text: str, lines: list[str]) -> ExtractedPharmacyBill:
    doc = ExtractedPharmacyBill()
    doc.pharmacy_name = rule_field(_org_name(lines[0])) if lines else missing_field()
    if (name := _search(r"Patient Name (.+?)(?: Bill No| UHID| Age /|$)", text)):
        doc.patient_name = rule_field(name)
    if (bill_no := _search(r"Bill No (\S+)", text)):
        doc.bill_no = rule_field(bill_no)
    if (bd := _parse_date(_search(rf"(?:^|\s)Date {_DATE_RE}", text))):
        doc.bill_date = rule_field(bd)
    for ln in lines:
        m = _PHARM_ROW.match(ln)
        if not m:
            continue
        line_valid = round(float(m.group(2)) * float(m.group(3)), 2) == float(m.group(4))
        doc.line_items.append(ExtractedPharmacyLine(
            drug_name=rule_field(m.group(1).strip()),
            quantity=rule_field(float(m.group(2))),
            mrp=rule_field(float(m.group(3))),
            amount=rule_field(float(m.group(4)), validated=line_valid),
        ))
    if (total := _line_amount(lines, "Total")) is not None:
        reconciles = bool(doc.line_items
                          and round(sum(li.amount.value for li in doc.line_items), 2) == total)
        doc.total = rule_field(total, validated=reconciles)
    return doc


def _extract_prescription(text: str, lines: list[str]) -> ExtractedPrescription:
    doc = ExtractedPrescription()
    doc.patient = _patient(text)
    if (bd := _parse_date(_search(rf"(?:^|\s)Date {_DATE_RE}", text))):
        doc.prescription_date = rule_field(bd)
    if (doctor := _search(r"Prescribing Doctor (.+?)(?:\s*\(|$)", text)):
        doc.doctor = rule_field(doctor)
    for i, ln in enumerate(lines):
        if ln.strip().lower() == "diagnosis" and i + 1 < len(lines):
            doc.diagnosis_text = rule_field(lines[i + 1].strip())
            break
    for ln in lines:
        m = _RX_ROW.match(ln)
        if m:
            doc.medications.append(rule_field(m.group(1).strip()))
    return doc


def _extract_lab(text: str, lines: list[str]) -> ExtractedLabReport:
    doc = ExtractedLabReport()
    doc.lab_name = rule_field(_org_name(lines[0])) if lines else missing_field()
    doc.patient = _patient(text)
    if (panel := _search(r"Panel (.+)", text)):  # to end of that line ('.' stops at newline)
        doc.panel_name = rule_field(panel)
    if (rd := _parse_date(_search(rf"Report Date {_DATE_RE}", text))):
        doc.report_date = rule_field(rd)
    # result row: the line after the "Test Result Unit Reference Range Flag" header
    panel_val = doc.panel_name.value
    for i, ln in enumerate(lines):
        if ln.startswith("Test Result") and i + 1 < len(lines):
            row = lines[i + 1]
            value = row
            if panel_val and row.startswith(panel_val):
                value = row[len(panel_val):].strip()
            value = re.sub(r"(\s*-)+\s*$", "", value).strip()  # drop trailing unit/ref/flag dashes
            doc.results.append(ExtractedLabResult(
                test_name=rule_field(panel_val or "result"),
                value=rule_field(value),
            ))
            break
    return doc


_EXTRACTORS = {
    DocType.hospital_bill: _extract_hospital_bill,
    DocType.discharge_summary: _extract_discharge,
    DocType.pharmacy_bill: _extract_pharmacy,
    DocType.prescription: _extract_prescription,
    DocType.lab_report: _extract_lab,
}


def extract_document(doc_type: DocType, text: str) -> ExtractedDocument | None:
    """Run the deterministic layer for one document's text. Returns None for `other`."""
    fn = _EXTRACTORS.get(doc_type)
    if fn is None:
        return None
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return fn(text, lines)


def extract_claim(claim_ir: ClaimIR, records: list[DocumentRecord]) -> list[DocumentRecord]:
    """Fill each `DocumentRecord.extracted` from the deterministic layer (in place)."""
    by_page = {p.page: p for p in claim_ir.pages}
    for rec in records:
        text = "\n".join(by_page[pg].text for pg in rec.page_range if pg in by_page)
        rec.extracted = extract_document(rec.doc_type, text)
    return records
