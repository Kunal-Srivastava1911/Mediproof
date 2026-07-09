"""Fictional catalogs for synthetic claim generation.

Brand & legal safety (plan §5, §11): every institution here is invented. No real hospital,
insurer, lab, or pharmacy names or logos. Clinical content (ICD-10, drugs, charge
structures) is realistic but generic. Every rendered page carries a SPECIMEN watermark.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Institution:
    name: str
    address: str
    registration_no: str
    template_id: str  # drives the unseen-template eval split (plan §7)


# 5 fictional hospitals. `template_id` doubles as the letterhead-style key; the eval split
# (plan §7) trains on hospital-a..c and holds out hospital-d/e.
HOSPITALS: list[Institution] = [
    Institution("Sunrise Multispeciality Hospital", "14 MG Road, Indiranagar, Bengaluru 560038",
                "KA/HOSP/2011/4471", "hospital-a"),
    Institution("Greenfield Care Institute", "Plot 22, Sector 18, Noida 201301",
                "UP/HOSP/2014/8820", "hospital-b"),
    Institution("Lotus Valley Health Centre", "56 Anna Salai, Chennai 600002",
                "TN/HOSP/2009/1132", "hospital-c"),
    Institution("Silverline Medical College Hospital", "3 FC Road, Pune 411004",
                "MH/HOSP/2016/6654", "hospital-d"),
    Institution("Meridian Speciality Hospital", "9 Park Street, Kolkata 700016",
                "WB/HOSP/2013/3390", "hospital-e"),
]

LABS: list[Institution] = [
    Institution("PrecisionPath Diagnostics", "22 Residency Road, Bengaluru 560025",
                "KA/LAB/2015/771", "lab-a"),
    Institution("ClearView Labs", "8 Ring Road, Delhi 110024", "DL/LAB/2017/220", "lab-b"),
]

PHARMACIES: list[Institution] = [
    Institution("WellMed Pharmacy", "Shop 4, MG Road, Bengaluru 560001",
                "KA/PHARM/2018/9901", "pharmacy-a"),
    Institution("CarePlus Chemists", "12 Station Road, Noida 201301",
                "UP/PHARM/2019/5540", "pharmacy-b"),
]


@dataclass(frozen=True)
class Drug:
    name: str
    strength: str
    unit_mrp: float  # per unit / strip


# Generic drug names (open Jan Aushadhi / NLEM style). No brands.
DRUGS: dict[str, Drug] = {
    "paracetamol": Drug("Paracetamol", "500mg", 18.0),
    "amoxiclav": Drug("Amoxicillin + Clavulanate", "625mg", 142.0),
    "ceftriaxone": Drug("Ceftriaxone Injection", "1g", 78.0),
    "pantoprazole": Drug("Pantoprazole", "40mg", 96.0),
    "ondansetron": Drug("Ondansetron", "4mg", 44.0),
    "metronidazole": Drug("Metronidazole", "400mg", 22.0),
    "atorvastatin": Drug("Atorvastatin", "10mg", 65.0),
    "aspirin": Drug("Aspirin", "75mg", 12.0),
    "clopidogrel": Drug("Clopidogrel", "75mg", 88.0),
    "enoxaparin": Drug("Enoxaparin Injection", "40mg", 310.0),
    "insulin_reg": Drug("Regular Insulin", "40IU/ml", 145.0),
    "metformin": Drug("Metformin", "500mg", 24.0),
    "tramadol": Drug("Tramadol", "50mg", 33.0),
    "diclofenac": Drug("Diclofenac", "50mg", 19.0),
}


@dataclass(frozen=True)
class Scenario:
    """A coherent clinical episode: diagnosis + ICD + procedures + typical drugs + labs.

    Coherence here is what lets the audit engine later detect *incoherence* injected as a
    fault (drug/diagnosis mismatch, missing lab). No clinical inference is ever done on
    real data — this only shapes synthetic ground truth.
    """

    key: str
    diagnosis_text: str
    icd10_codes: list[str]
    procedures: list[str]
    drug_keys: list[str]
    lab_panels: list[str]
    los_days: int = 3  # typical length of stay


SCENARIOS: list[Scenario] = [
    Scenario(
        key="appendicitis",
        diagnosis_text="Acute appendicitis with localised peritonitis",
        icd10_codes=["K35.80"],
        procedures=["Laparoscopic appendicectomy"],
        drug_keys=["ceftriaxone", "metronidazole", "paracetamol", "pantoprazole", "ondansetron"],
        lab_panels=["Complete Blood Count", "Serum Electrolytes"],
        los_days=3,
    ),
    Scenario(
        key="acute_mi",
        diagnosis_text="Acute inferior wall myocardial infarction",
        icd10_codes=["I21.19"],
        procedures=["Coronary angiography", "PTCA with drug-eluting stent"],
        drug_keys=["aspirin", "clopidogrel", "atorvastatin", "enoxaparin", "pantoprazole"],
        lab_panels=["Cardiac Troponin I", "Lipid Profile", "Complete Blood Count"],
        los_days=4,
    ),
    Scenario(
        key="pneumonia",
        diagnosis_text="Community-acquired pneumonia, right lower lobe",
        icd10_codes=["J18.1"],
        procedures=["Chest physiotherapy"],
        drug_keys=["amoxiclav", "paracetamol", "pantoprazole", "ondansetron"],
        lab_panels=["Complete Blood Count", "C-Reactive Protein"],
        los_days=4,
    ),
    Scenario(
        key="dka",
        diagnosis_text="Diabetic ketoacidosis in type 2 diabetes mellitus",
        icd10_codes=["E11.10"],
        procedures=["IV fluid and insulin management"],
        drug_keys=["insulin_reg", "metformin", "pantoprazole", "ondansetron"],
        lab_panels=["Blood Glucose", "Serum Electrolytes", "Arterial Blood Gas"],
        los_days=3,
    ),
]


@dataclass(frozen=True)
class ChargeItem:
    description: str
    category: str
    unit_price: float
    per_day: bool = False
    non_payable: bool = False


# Standard-ish hospitalisation charge lines. Consumable/admin items flagged non_payable per
# an IRDAI-aligned exclusions list (plan §M4, §11).
BASE_CHARGES: list[ChargeItem] = [
    ChargeItem("Room Rent (Semi-Private)", "room", 3500.0, per_day=True),
    ChargeItem("Nursing Charges", "professional_fee", 800.0, per_day=True),
    ChargeItem("Doctor Visit / Consultation", "professional_fee", 1200.0, per_day=True),
    ChargeItem("Investigation Charges", "investigation", 2400.0),
    ChargeItem("Surgeon / Procedure Fee", "procedure", 22000.0),
    ChargeItem("OT Charges", "procedure", 9000.0),
    ChargeItem("Pharmacy (in-patient)", "pharmacy", 6400.0),
]

NON_PAYABLE_CONSUMABLES: list[ChargeItem] = [
    ChargeItem("Gloves & Disposables", "consumable", 450.0, non_payable=True),
    ChargeItem("Administrative / Record Charges", "consumable", 300.0, non_payable=True),
    ChargeItem("Attendant Meal Charges", "consumable", 600.0, non_payable=True),
]


# Small curated set for lab-result value generation (test -> (unit, ref_range, normal_value)).
LAB_TESTS: dict[str, tuple[str, str, str]] = {
    "Complete Blood Count": ("", "", "Hb 13.4 g/dL, TLC 8600 /µL, Platelets 2.4 lakh/µL"),
    "Serum Electrolytes": ("", "", "Na 138 mmol/L, K 4.1 mmol/L, Cl 101 mmol/L"),
    "Cardiac Troponin I": ("ng/mL", "< 0.04", "2.86"),
    "Lipid Profile": ("mg/dL", "", "Total 214, LDL 142, HDL 38, TG 176"),
    "C-Reactive Protein": ("mg/L", "< 5", "48"),
    "Blood Glucose": ("mg/dL", "70–140", "412"),
    "Arterial Blood Gas": ("", "", "pH 7.21, HCO3 12 mmol/L, pCO2 28 mmHg"),
    "Cardiac Troponin": ("ng/mL", "< 0.04", "2.86"),
}


DOCTORS: list[tuple[str, str]] = [
    ("Dr. A. Nair", "KMC/34112"),
    ("Dr. S. Reddy", "TNMC/55210"),
    ("Dr. P. Banerjee", "WBMC/11987"),
    ("Dr. R. Kulkarni", "MMC/40233"),
    ("Dr. M. Iyer", "KMC/29981"),
]


def money(x: float) -> float:
    """Round to 2 decimals so synthetic arithmetic stays exact."""
    return round(x + 1e-9, 2)
