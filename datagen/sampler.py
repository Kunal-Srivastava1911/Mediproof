"""Deterministic sampler: seed -> one coherent ClaimGroundTruth.

Coherence guarantees (a *clean* file has zero faults):
  * one canonical patient appears identically on every document
  * admission_date < discharge_date, pharmacy dates inside the admission window
  * bill line items sum exactly to subtotal/total (arithmetic is exact)
  * drugs, procedures and labs all come from one clinical scenario

Same seed -> byte-identical ground truth (CLAUDE.md rule 6).
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from faker import Faker

from datagen import fake_data as fd
from schemas.common import DocType, Gender
from schemas.ground_truth import (
    BillCategory,
    BillLineItem,
    ClaimGroundTruth,
    DischargeSummaryGT,
    HospitalBillGT,
    HospitalInfo,
    LabReportGT,
    LabResult,
    Medication,
    PatientInfo,
    PharmacyBillGT,
    PharmacyLineItem,
    PrescriptionGT,
)

# Fixed anchor so generated dates depend only on the seed, never on wall-clock time
# (CLAUDE.md rule 6: same seed -> byte-identical ground truth).
REFERENCE_DATE = date(2025, 1, 1)


def _patient(rng: random.Random, fake: Faker) -> PatientInfo:
    gender = rng.choice([Gender.male, Gender.female])
    name = fake.name_male() if gender is Gender.male else fake.name_female()
    return PatientInfo(
        name=name,
        age=rng.randint(21, 78),
        gender=gender,
        patient_id=f"UHID{rng.randint(100000, 999999)}",
        phone=f"9{rng.randint(100000000, 999999999)}",
    )


def _hospital_info(inst: fd.Institution) -> HospitalInfo:
    return HospitalInfo(name=inst.name, address=inst.address, registration_no=inst.registration_no)


def _build_bill(
    rng: random.Random, patient: PatientInfo, hospital: fd.Institution,
    scenario: fd.Scenario, admit: date, discharge: date, doc_id: str,
) -> HospitalBillGT:
    los = max(1, (discharge - admit).days)
    items: list[BillLineItem] = []
    for ch in fd.BASE_CHARGES:
        qty = los if ch.per_day else 1
        # small deterministic jitter on unit price (±8%)
        unit = fd.money(ch.unit_price * (1 + rng.uniform(-0.08, 0.08)))
        items.append(BillLineItem(
            description=ch.description, category=BillCategory(ch.category),
            quantity=qty, unit_price=unit, amount=fd.money(unit * qty),
            is_non_payable=ch.non_payable,
        ))
    for ch in rng.sample(fd.NON_PAYABLE_CONSUMABLES, k=2):
        items.append(BillLineItem(
            description=ch.description, category=BillCategory(ch.category),
            quantity=1, unit_price=ch.unit_price, amount=ch.unit_price, is_non_payable=True,
        ))

    subtotal = fd.money(sum(i.amount for i in items))
    discount = fd.money(subtotal * rng.choice([0.0, 0.0, 0.05]))
    tax = fd.money((subtotal - discount) * 0.05)
    total = fd.money(subtotal - discount + tax)
    return HospitalBillGT(
        document_id=doc_id, template_id=hospital.template_id,
        hospital=_hospital_info(hospital), patient=patient,
        bill_no=f"INV/{admit.year}/{rng.randint(1000, 9999)}",
        bill_date=discharge, admission_date=admit, discharge_date=discharge,
        line_items=items, subtotal=subtotal, discount=discount, tax=tax, total=total,
    )


def _build_discharge(
    patient: PatientInfo, hospital: fd.Institution, scenario: fd.Scenario,
    admit: date, discharge: date, doctor: tuple[str, str], doc_id: str,
) -> DischargeSummaryGT:
    return DischargeSummaryGT(
        document_id=doc_id, template_id=hospital.template_id,
        hospital=_hospital_info(hospital), patient=patient,
        admission_date=admit, discharge_date=discharge,
        diagnosis_text=scenario.diagnosis_text, icd10_codes=list(scenario.icd10_codes),
        procedures=list(scenario.procedures), treating_doctor=doctor[0], doctor_reg_no=doctor[1],
    )


def _build_pharmacy(
    rng: random.Random, patient: PatientInfo, pharmacy: fd.Institution,
    scenario: fd.Scenario, admit: date, discharge: date, doc_id: str,
) -> PharmacyBillGT:
    bill_date = admit + timedelta(days=rng.randint(0, max(0, (discharge - admit).days)))
    lines: list[PharmacyLineItem] = []
    for key in scenario.drug_keys:
        drug = fd.DRUGS[key]
        qty = rng.randint(1, 3)
        lines.append(PharmacyLineItem(
            drug_name=f"{drug.name} {drug.strength}",
            batch_no=f"B{rng.randint(10000, 99999)}",
            quantity=qty, mrp=drug.unit_mrp, amount=fd.money(drug.unit_mrp * qty),
        ))
    total = fd.money(sum(line.amount for line in lines))
    return PharmacyBillGT(
        document_id=doc_id, template_id=pharmacy.template_id,
        pharmacy_name=pharmacy.name, pharmacy_address=pharmacy.address,
        bill_no=f"PH/{bill_date.year}/{rng.randint(1000, 9999)}", bill_date=bill_date,
        patient_name=patient.name, prescription_ref=f"RX{rng.randint(1000, 9999)}",
        line_items=lines, total=total,
    )


def _build_prescription(
    patient: PatientInfo, hospital: fd.Institution, scenario: fd.Scenario,
    discharge: date, doctor: tuple[str, str], doc_id: str,
) -> PrescriptionGT:
    meds = [
        Medication(drug_name=f"{fd.DRUGS[k].name} {fd.DRUGS[k].strength}",
                   frequency="1-0-1", duration="5 days")
        for k in scenario.drug_keys
    ]
    return PrescriptionGT(
        document_id=doc_id, template_id=hospital.template_id,
        hospital=_hospital_info(hospital), patient=patient, prescription_date=discharge,
        doctor=doctor[0], doctor_reg_no=doctor[1],
        diagnosis_text=scenario.diagnosis_text, medications=meds,
    )


def _build_lab(
    patient: PatientInfo, lab: fd.Institution, panel: str, report_date: date,
    doctor: tuple[str, str], doc_id: str,
) -> LabReportGT:
    unit, ref, value = fd.LAB_TESTS.get(panel, ("", "", "Within normal limits"))
    return LabReportGT(
        document_id=doc_id, template_id=lab.template_id, lab_name=lab.name, patient=patient,
        panel_name=panel,
        results=[LabResult(test_name=panel, value=value, unit=unit or None,
                           reference_range=ref or None)],
        report_date=report_date, referring_doctor=doctor[0],
    )


def sample_claim(seed: int, claim_id: str | None = None) -> ClaimGroundTruth:
    """Build one coherent, fault-free claim ground truth from `seed`."""
    rng = random.Random(seed)
    fake = Faker("en_IN")
    fake.seed_instance(seed)

    claim_id = claim_id or f"CLAIM-{seed:06d}"
    scenario = rng.choice(fd.SCENARIOS)
    hospital = rng.choice(fd.HOSPITALS)
    pharmacy = rng.choice(fd.PHARMACIES)
    lab = rng.choice(fd.LABS)
    doctor = rng.choice(fd.DOCTORS)
    patient = _patient(rng, fake)

    admit = REFERENCE_DATE - timedelta(days=rng.randint(20, 120))
    discharge = admit + timedelta(days=scenario.los_days)

    bill = _build_bill(rng, patient, hospital, scenario, admit, discharge, f"{claim_id}-BILL")
    discharge_doc = _build_discharge(patient, hospital, scenario, admit, discharge, doctor,
                                     f"{claim_id}-DISCH")
    pharmacy_doc = _build_pharmacy(rng, patient, pharmacy, scenario, admit, discharge,
                                   f"{claim_id}-PHARM")
    prescription = _build_prescription(patient, hospital, scenario, discharge, doctor,
                                       f"{claim_id}-RX")
    labs = [
        _build_lab(patient, lab, panel, discharge, doctor, f"{claim_id}-LAB{i}")
        for i, panel in enumerate(scenario.lab_panels)
    ]

    documents = [bill, discharge_doc, pharmacy_doc, prescription, *labs]
    template_meta = {
        DocType.hospital_bill.value: hospital.template_id,
        DocType.discharge_summary.value: hospital.template_id,
        DocType.pharmacy_bill.value: pharmacy.template_id,
        DocType.prescription.value: hospital.template_id,
        DocType.lab_report.value: lab.template_id,
    }
    return ClaimGroundTruth(
        claim_id=claim_id, seed=seed, patient=patient, documents=documents,
        faults=[], template_meta=template_meta,
    )
