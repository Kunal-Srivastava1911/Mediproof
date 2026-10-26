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
| `claim_form_dates` | warning | claim-form admission/discharge differs from the bill |
| `pharmacy_outside_stay` | warning | pharmacy bill dated outside the stay |

The held-out families (ICU days vs the narrative, billed imaging with no report, one-letter
name variants) intentionally have no rule — see `schemas.ground_truth.HELD_OUT_FAULTS`.

The drug↔diagnosis check uses **only** a small curated marker map (`rules.yaml`), mirrored
from datagen with a parity test — anything outside the set is never flagged (no general
clinical inference, plan §M4). Prescription↔pharmacy matching and tampering signals (PDF
metadata, font inconsistency; copy-move is cut-line 2) are the documented next rules.

## Agent auditor (`agents.py` → `verify.py`)

Rules only find what someone anticipated. Five specialist Claude agents — **billing,
clinical record, pharmacy, timeline, identity** — each read the whole file (one shared,
prompt-cached dossier of every document's text, narrative included) and propose review
items. A **skeptic agent** then cross-examines every proposal. Nothing an agent says is
shown as-is; `verify.py` turns proposals into findings only through:

1. **Grounding** — every quote must appear in the document it cites and is located on the
   page (bbox evidence). An ungrounded quote scores 0 and is held back.
2. **Code check** — dates must really differ / fall outside the stay, counts must really
   differ, a "missing" report's keyword must really be absent from every other document.
3. **Skeptic verdict.**

`verifier_score = 0.1 + 0.45·check + 0.45·skeptic` (grounding gates it; absent check or
skeptic = neutral 0.5). Below the calibrated threshold (`calibration.json`, written by
`evals/conformal.py`; default 0.6) a finding is `held_back`: reviewers see it, patients
never do. An agent finding that repeats a rule finding is folded into it as corroboration.

Without recorded fixtures and with `LLM_LIVE` off, the auditor is skipped and the claim's
`audit.note` says so — the rule pack still runs.

`timeline.py` builds the claim's shared **timeline** and **evidence map** (facts × documents,
the within-claim evidence graph) from extracted fields and marks the cells findings touch.

## Verified

- **Every injected fault type raises its expected finding** (end-to-end test over all 7).
- **Zero warning/critical findings on a clean claim** — the false-positive rate a buyer
  cares about. (Clean files still surface the `info` non-payable note.)

**DoD:** per-fault-type precision/recall + clean-file FP rate reported by `make eval`.
Run `make test-m4`.
