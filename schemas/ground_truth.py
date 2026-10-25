"""Ground-truth contracts produced by datagen.

Ground truth is *certain* — unlike extraction output (see documents.py) these models hold
plain typed values, no confidence. datagen renders a document PDF from one of these and
writes the model itself out as the answer key the eval harness scores against.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from schemas.common import DocType, Gender, Severity
from schemas.findings import FindingType

# --------------------------------------------------------------------------- shared


class PatientInfo(BaseModel):
    name: str
    age: int = Field(ge=0, le=120)
    gender: Gender
    patient_id: str | None = None
    phone: str | None = None


class HospitalInfo(BaseModel):
    name: str
    address: str
    registration_no: str | None = None


class BillCategory(str, Enum):
    room = "room"
    procedure = "procedure"
    consumable = "consumable"
    pharmacy = "pharmacy"
    investigation = "investigation"
    professional_fee = "professional_fee"
    other = "other"


class BillLineItem(BaseModel):
    description: str
    category: BillCategory
    quantity: float = Field(default=1, ge=0)
    unit_price: float = Field(ge=0)
    amount: float = Field(ge=0)
    is_non_payable: bool = False


class PharmacyLineItem(BaseModel):
    drug_name: str
    batch_no: str | None = None
    quantity: float = Field(default=1, ge=0)
    mrp: float = Field(ge=0)
    amount: float = Field(ge=0)


class Medication(BaseModel):
    drug_name: str
    strength: str | None = None
    frequency: str | None = None
    duration: str | None = None


class LabResult(BaseModel):
    test_name: str
    value: str
    unit: str | None = None
    reference_range: str | None = None
    flag: str | None = Field(default=None, description="H/L/None relative to reference range")


# --------------------------------------------------------------------- per doc type


class _DocBase(BaseModel):
    """Common envelope every ground-truth document carries."""

    document_id: str
    template_id: str = Field(description="which HTML template rendered this — drives the "
                             "unseen-template eval split (plan §7)")


class HospitalBillGT(_DocBase):
    doc_type: Literal[DocType.hospital_bill] = DocType.hospital_bill
    hospital: HospitalInfo
    patient: PatientInfo
    bill_no: str
    bill_date: date
    admission_date: date
    discharge_date: date
    line_items: list[BillLineItem]
    subtotal: float
    discount: float = 0.0
    tax: float = 0.0
    total: float


class DischargeSummaryGT(_DocBase):
    doc_type: Literal[DocType.discharge_summary] = DocType.discharge_summary
    hospital: HospitalInfo
    patient: PatientInfo
    admission_date: date
    discharge_date: date
    diagnosis_text: str
    icd10_codes: list[str] = Field(default_factory=list)
    procedures: list[str] = Field(default_factory=list)
    treating_doctor: str
    doctor_reg_no: str | None = None
    course_in_hospital: str = Field(default="", description="per-claim clinical narrative")
    icu_days: int = Field(default=0, ge=0, description="days in ICU per the narrative")
    imaging: list[str] = Field(default_factory=list, description="imaging studies mentioned")


class PharmacyBillGT(_DocBase):
    doc_type: Literal[DocType.pharmacy_bill] = DocType.pharmacy_bill
    pharmacy_name: str
    pharmacy_address: str
    bill_no: str
    bill_date: date
    patient_name: str
    prescription_ref: str | None = None
    line_items: list[PharmacyLineItem]
    total: float


class LabReportGT(_DocBase):
    doc_type: Literal[DocType.lab_report] = DocType.lab_report
    lab_name: str
    patient: PatientInfo
    panel_name: str
    results: list[LabResult]
    report_date: date
    referring_doctor: str | None = None
    kind: Literal["lab", "imaging"] = Field(
        default="lab", description="imaging reports reuse the lab layout with a radiology title")


class PrescriptionGT(_DocBase):
    doc_type: Literal[DocType.prescription] = DocType.prescription
    hospital: HospitalInfo
    patient: PatientInfo
    prescription_date: date
    doctor: str
    doctor_reg_no: str | None = None
    diagnosis_text: str | None = None
    medications: list[Medication]


class ClaimFormGT(_DocBase):
    """The insured's claim form (Part A). Dates are written DD/MM/YYYY, as on real forms."""

    doc_type: Literal[DocType.claim_form] = DocType.claim_form
    insured_name: str
    policy_no: str
    hospital_name: str
    admission_date: date
    discharge_date: date
    diagnosis_text: str
    claimed_amount: float


# --------------------------------------------------------------- faults & claim


class FaultType(str, Enum):
    """The seeded problems (~10% of files). Each maps to the finding the audit engine
    should raise, so precision/recall is scoreable (plan §5, §7)."""

    inflated_line_item = "inflated_line_item"
    date_mismatch = "date_mismatch"
    drug_diagnosis_mismatch = "drug_diagnosis_mismatch"
    missing_lab_report = "missing_lab_report"
    duplicate_billing = "duplicate_billing"
    name_mismatch = "name_mismatch"
    bill_arithmetic_error = "bill_arithmetic_error"
    # Cross-document semantic / temporal families.
    claim_form_date_mismatch = "claim_form_date_mismatch"
    pharmacy_after_discharge = "pharmacy_after_discharge"
    icu_days_mismatch = "icu_days_mismatch"
    missing_imaging_report = "missing_imaging_report"
    name_variant = "name_variant"


# Which finding a given seeded fault is expected to trigger (eval harness join key).
FAULT_TO_FINDING: dict[FaultType, FindingType] = {
    FaultType.inflated_line_item: FindingType.inflated_line_item,
    FaultType.date_mismatch: FindingType.date_inconsistent,
    FaultType.drug_diagnosis_mismatch: FindingType.drug_diagnosis_implausible,
    FaultType.missing_lab_report: FindingType.missing_lab_report,
    FaultType.duplicate_billing: FindingType.duplicate_line_item,
    FaultType.name_mismatch: FindingType.name_inconsistent,
    FaultType.bill_arithmetic_error: FindingType.bill_arithmetic_mismatch,
    FaultType.claim_form_date_mismatch: FindingType.date_inconsistent,
    FaultType.pharmacy_after_discharge: FindingType.temporal_inconsistency,
    FaultType.icu_days_mismatch: FindingType.unsupported_by_documentation,
    FaultType.missing_imaging_report: FindingType.missing_report,
    FaultType.name_variant: FindingType.name_inconsistent,
}

# Fault families the deterministic rule pack deliberately has NO rule for. The eval harness
# reports recall on these separately: it measures what the agent auditor catches that nobody
# wrote a rule for (the open-world split).
HELD_OUT_FAULTS: frozenset[FaultType] = frozenset({
    FaultType.icu_days_mismatch,
    FaultType.missing_imaging_report,
    FaultType.name_variant,
})


class FaultLabel(BaseModel):
    fault_type: FaultType
    severity: Severity
    description: str = Field(description="human-readable note, review-item language")
    document_ids: list[str] = Field(
        default_factory=list, description="documents the fault was injected into"
    )
    expected_finding: FindingType


# Discriminated union over doc_type, so reloading a claim routes each document to the exact
# model regardless of overlapping fields.
DocumentGT = Annotated[
    HospitalBillGT | DischargeSummaryGT | PharmacyBillGT | LabReportGT | PrescriptionGT
    | ClaimFormGT,
    Field(discriminator="doc_type"),
]


class ClaimGroundTruth(BaseModel):
    """The complete answer key for one generated claim file."""

    claim_id: str
    claim_type: str = "cashless_hospitalization"
    seed: int
    patient: PatientInfo = Field(description="canonical patient — docs may diverge iff a "
                                 "name/date fault is injected")
    documents: list[DocumentGT]
    faults: list[FaultLabel] = Field(default_factory=list)
    template_meta: dict[str, str] = Field(
        default_factory=dict, description="doc_type -> template_id, for the split enforcer"
    )

    @property
    def is_clean(self) -> bool:
        return not self.faults
