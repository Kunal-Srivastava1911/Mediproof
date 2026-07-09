"""Extraction-output contracts (M3 hybrid extraction).

Unlike ground_truth.py, every field here is an `ExtractedField` carrying confidence and
grounding evidence. M3 fills these; the HITL dashboard renders them; the audit engine
reads their `.value`. `None`/`confidence=0` is the defined "not extracted" state.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from schemas.common import DocType, ExtractedField, Gender
from schemas.ground_truth import BillCategory


class ExtractedPatient(BaseModel):
    name: ExtractedField[str] = Field(default_factory=ExtractedField)
    age: ExtractedField[int] = Field(default_factory=ExtractedField)
    gender: ExtractedField[Gender] = Field(default_factory=ExtractedField)
    patient_id: ExtractedField[str] = Field(default_factory=ExtractedField)


class ExtractedBillLine(BaseModel):
    description: ExtractedField[str] = Field(default_factory=ExtractedField)
    category: ExtractedField[BillCategory] = Field(default_factory=ExtractedField)
    quantity: ExtractedField[float] = Field(default_factory=ExtractedField)
    unit_price: ExtractedField[float] = Field(default_factory=ExtractedField)
    amount: ExtractedField[float] = Field(default_factory=ExtractedField)


class ExtractedHospitalBill(BaseModel):
    doc_type: Literal[DocType.hospital_bill] = DocType.hospital_bill
    hospital_name: ExtractedField[str] = Field(default_factory=ExtractedField)
    patient: ExtractedPatient = Field(default_factory=ExtractedPatient)
    bill_no: ExtractedField[str] = Field(default_factory=ExtractedField)
    bill_date: ExtractedField[date] = Field(default_factory=ExtractedField)
    admission_date: ExtractedField[date] = Field(default_factory=ExtractedField)
    discharge_date: ExtractedField[date] = Field(default_factory=ExtractedField)
    line_items: list[ExtractedBillLine] = Field(default_factory=list)
    subtotal: ExtractedField[float] = Field(default_factory=ExtractedField)
    discount: ExtractedField[float] = Field(default_factory=ExtractedField)
    tax: ExtractedField[float] = Field(default_factory=ExtractedField)
    total: ExtractedField[float] = Field(default_factory=ExtractedField)


class ExtractedDischargeSummary(BaseModel):
    doc_type: Literal[DocType.discharge_summary] = DocType.discharge_summary
    hospital_name: ExtractedField[str] = Field(default_factory=ExtractedField)
    patient: ExtractedPatient = Field(default_factory=ExtractedPatient)
    admission_date: ExtractedField[date] = Field(default_factory=ExtractedField)
    discharge_date: ExtractedField[date] = Field(default_factory=ExtractedField)
    diagnosis_text: ExtractedField[str] = Field(default_factory=ExtractedField)
    icd10_codes: list[ExtractedField[str]] = Field(default_factory=list)
    treating_doctor: ExtractedField[str] = Field(default_factory=ExtractedField)


class ExtractedPharmacyLine(BaseModel):
    drug_name: ExtractedField[str] = Field(default_factory=ExtractedField)
    quantity: ExtractedField[float] = Field(default_factory=ExtractedField)
    mrp: ExtractedField[float] = Field(default_factory=ExtractedField)
    amount: ExtractedField[float] = Field(default_factory=ExtractedField)


class ExtractedPharmacyBill(BaseModel):
    doc_type: Literal[DocType.pharmacy_bill] = DocType.pharmacy_bill
    pharmacy_name: ExtractedField[str] = Field(default_factory=ExtractedField)
    bill_no: ExtractedField[str] = Field(default_factory=ExtractedField)
    bill_date: ExtractedField[date] = Field(default_factory=ExtractedField)
    patient_name: ExtractedField[str] = Field(default_factory=ExtractedField)
    line_items: list[ExtractedPharmacyLine] = Field(default_factory=list)
    total: ExtractedField[float] = Field(default_factory=ExtractedField)


class ExtractedLabResult(BaseModel):
    test_name: ExtractedField[str] = Field(default_factory=ExtractedField)
    value: ExtractedField[str] = Field(default_factory=ExtractedField)
    unit: ExtractedField[str] = Field(default_factory=ExtractedField)
    reference_range: ExtractedField[str] = Field(default_factory=ExtractedField)


class ExtractedLabReport(BaseModel):
    doc_type: Literal[DocType.lab_report] = DocType.lab_report
    lab_name: ExtractedField[str] = Field(default_factory=ExtractedField)
    patient: ExtractedPatient = Field(default_factory=ExtractedPatient)
    panel_name: ExtractedField[str] = Field(default_factory=ExtractedField)
    results: list[ExtractedLabResult] = Field(default_factory=list)
    report_date: ExtractedField[date] = Field(default_factory=ExtractedField)


class ExtractedPrescription(BaseModel):
    doc_type: Literal[DocType.prescription] = DocType.prescription
    patient: ExtractedPatient = Field(default_factory=ExtractedPatient)
    prescription_date: ExtractedField[date] = Field(default_factory=ExtractedField)
    doctor: ExtractedField[str] = Field(default_factory=ExtractedField)
    diagnosis_text: ExtractedField[str] = Field(default_factory=ExtractedField)
    medications: list[ExtractedField[str]] = Field(default_factory=list)


ExtractedDocument = Annotated[
    ExtractedHospitalBill
    | ExtractedDischargeSummary
    | ExtractedPharmacyBill
    | ExtractedLabReport
    | ExtractedPrescription,
    Field(discriminator="doc_type"),
]
