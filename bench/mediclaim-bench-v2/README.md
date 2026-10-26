# MediClaim-Bench v2 (synthetic)

240 synthetic Indian health-insurance claim files: **121 clean, 119 with one seeded,
labelled fault** — ~10 per fault family across all 12 families, including 3 **held-out**
families the rule pack deliberately has no rule for (★).

**Synthetic data only.** Every person, hospital, pharmacy and policy number is invented;
every rendered page carries a `SPECIMEN — SYNTHETIC DATA` watermark.

## Files

- `index.json` — one row per claim: `claim_id`, `seed`, `template_meta`, `faults`
- `CLAIM-xxxxxx.json` — the full ground truth (`schemas.ground_truth.ClaimGroundTruth`):
  every document's values plus the `FaultLabel` (fault type, documents touched, the
  `FindingType` the audit engine should raise)

PDFs are not committed: each claim re-renders byte-identically from its seed.

## Fault families

| Family | Expected finding | Needs |
|---|---|---|
| inflated_line_item, bill_arithmetic_error, duplicate_billing | bill checks | — |
| date_mismatch, claim_form_date_mismatch | `date_inconsistent` | — |
| pharmacy_after_discharge | `temporal_inconsistency` | — |
| name_mismatch | `name_inconsistent` | — |
| missing_lab_report | `missing_lab_report` | — |
| drug_diagnosis_mismatch | `drug_diagnosis_implausible` | a non-cardiac claim |
| icu_days_mismatch ★ | `unsupported_by_documentation` | an ICU stay |
| missing_imaging_report ★ | `missing_report` | an imaging study |
| name_variant ★ | `name_inconsistent` | — |

## Regenerate / evaluate

```bash
python -m datagen.cli bulk --count 240 --start-seed 5000 --fault-rate 0.5 --balanced \
    --gt-only --out bench/mediclaim-bench-v2
python -m evals.cli --bench bench/mediclaim-bench-v2 --limit 60     # renders + scores
```
