# M4 — Cross-Document Audit Engine

**In:** the claim's extracted documents (`list[DocumentRecord]`). **Out:** `list[Finding]` —
severity-scored review items, each linking its bbox evidence.

**Framing (non-negotiable, CLAUDE.md):** findings are *documentation review items*, never
accusations. No "fraud"/"reject" language. Every finding links its evidence so a human judges.

## How it works

`rules.yaml` is a **config-driven rule pack**: each rule declares its finding type, severity,
reviewer-facing title, and params. The detection logic per rule id is a registered function
in `audit.py`. `run_audit(docs)` runs the enabled rules and returns `Finding`s with sequential
ids (`F-001`, …) and evidence pulled from the offending fields' grounded boxes.

## Rules (each maps to a scored fault type — plan §5/§7)

| Rule | Severity | Catches (injected fault) |
|------|----------|--------------------------|
| `name_inconsistent` | warning | patient name differs across documents (fuzzy) |
| `date_inconsistent` | warning | bill vs discharge admission/discharge dates differ |
| `bill_arithmetic_mismatch` | warning | total ≠ subtotal − discount + tax |
| `inflated_line_item` | critical | line amount ≠ quantity × unit price |
| `duplicate_line_item` | warning | same (description, amount) billed twice |
| `missing_lab_report` | warning | investigation billed but no lab report present |
| `drug_diagnosis_implausible` | critical | curated marker drug without a justifying ICD |
| `non_payable_consumable` | info | standard non-payable consumable billed |

The drug↔diagnosis check uses **only** a small curated marker map (`rules.yaml`), mirrored
from datagen with a parity test — anything outside the set is never flagged (no general
clinical inference, plan §M4). Prescription↔pharmacy matching and tampering signals (PDF
metadata, font inconsistency; copy-move is cut-line 2) are the documented next rules.

## Verified

- **Every injected fault type raises its expected finding** (end-to-end test over all 7).
- **Zero warning/critical findings on a clean claim** — the false-positive rate a buyer
  cares about. (Clean files still surface the `info` non-payable note.)

**DoD:** per-fault-type precision/recall + clean-file FP rate reported by `make eval`.
Run `make test-m4`.
