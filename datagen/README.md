# datagen/ — MediClaim-Bench synthetic generator

Turns a **seed** into a coherent synthetic claim file: a set of PDFs plus a ground-truth
JSON answer key. Fully deterministic — the same seed reproduces byte-identical ground truth
(CLAUDE.md rule 6).

## Commands

```bash
make datagen-sample                              # one clean claim -> data/sample/  (W1 DoD)
python -m datagen.cli sample --fault inflated_line_item   # force a specific seeded fault
python -m datagen.cli bulk --count 300 --fault-rate 0.1   # benchmark set (~10% faulty)
python -m datagen.regolden                       # regenerate committed golden files (deliberate)
```

## Layout

| File | Role |
|------|------|
| `fake_data.py` | fictional hospitals/labs/pharmacies, generic drugs, ICD-10, charge structures, clinical scenarios, curated drug↔diagnosis markers |
| `sampler.py` | seed → one coherent `ClaimGroundTruth` (patient consistent, dates ordered, bill arithmetic exact) |
| `faults.py` | seeds one **isolated** fault into a clean claim and records its `FaultLabel` (+ the `FindingType` M4 must raise) |
| `templates/` | Jinja HTML + CSS letterheads (bill · discharge · pharmacy · lab · prescription) rendered to A4 |
| `render.py` | HTML → PDF via headless Chromium (Playwright); merges per-doc PDFs into `claim.pdf` |
| `cli.py` | `sample` / `bulk` entry points |

## Fault injection (plan §5)

`bulk` seeds a problem into ~10% of files; each carries a `FaultLabel` the eval harness
scores the audit engine against. Every fault is **isolated** — it triggers exactly one
finding type (e.g. an inflated *line* breaks `amount == qty × unit_price` but the claim
total is re-reconciled so it isn't *also* an arithmetic mismatch).

| `FaultType` | expected `FindingType` |
|-------------|------------------------|
| `inflated_line_item` | `inflated_line_item` |
| `bill_arithmetic_error` | `bill_arithmetic_mismatch` |
| `duplicate_billing` | `duplicate_line_item` |
| `date_mismatch` | `date_inconsistent` |
| `name_mismatch` | `name_inconsistent` |
| `missing_lab_report` | `missing_lab_report` |
| `drug_diagnosis_mismatch` | `drug_diagnosis_implausible` |

## Coherence guarantees (a *clean* file)

- one canonical patient on every document
- `admission_date < discharge_date`; pharmacy dates within the admission window
- bill line items sum exactly to subtotal/total
- drugs, procedures and labs all drawn from one clinical scenario

## Safety

Every institution is fictional; every page carries a `SPECIMEN — SYNTHETIC DATA`
watermark whose region is masked out of OCR evaluation (plan §5).

## Done (W1 · W2) / Next

- ✅ **W1** — bill, discharge, pharmacy templates; deterministic sampler; merged claim PDF; golden tests
- ✅ **W2** — lab + prescription templates; deterministic **fault injection** (7 fault types, each
  isolated + labelled); `bulk --fault-rate`; `sample --fault`
- ⬜ claim-form / ID / pre-auth templates (need new ground-truth models — a human-owned schema change);
  Augraphy degradation for the scanned-image OCR path

Run `make test-datagen`.
