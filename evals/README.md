# evals/ — evaluation harness

`make eval` renders a synthetic claim set, runs the full pipeline, scores it against ground
truth, and **writes the benchmark tables into the README** (between the `BENCHMARK` markers)
and `evals/RESULTS.md`. Everything is seed-driven, so the numbers reproduce exactly.

```bash
make eval            # or: ./run.ps1 eval  /  python -m evals.cli         (offline, replay)
make eval-live       # live Claude: calibrate the threshold, then evaluate (needs a key)
python -m evals.cli --bench bench/mediclaim-bench-v2 --limit 60       # committed benchmark
```

## What it measures (plan §7)

- **Classification** — document-type accuracy of the P0 segmenter.
- **Field extraction** — exact-match and normalized-match (dates/amounts canonicalized) vs
  ground truth, overall and per document type.
- **Audit engine, open-world** — recall per fault family for **rules only** vs **rules +
  verified agents**, reported separately for *seen* families and *held-out* ones (★, no rule
  was written for them — `schemas.ground_truth.HELD_OUT_FAULTS`). Plus severe items shown on
  clean files (rules vs agents), clean claims showing any agent item, items held back, and
  Claude calls/cost.
- **Certified false-flag rate** — `--calibrate N` runs N *separate* clean claims, then
  `conformal.py` (conformal risk control) picks the verifier threshold so that
  P(a clean claim shows ≥ 1 agent item) ≤ α, and writes `pipeline/m4_audit/calibration.json`
  before the evaluation runs. The guarantee is for claims like the calibration set
  (synthetic); on real files it is an estimate.
- **Coverage–accuracy curve** (headline) — accuracy of auto-accepted fields as a function of
  the % routed to human review, ordered by confidence.
- **Hybrid unit economics** — share of fields filled deterministically vs LLM calls made, and
  median latency; the "hybrid beats pure-LLM" argument.

## Files

| File | Role |
|------|------|
| `harness.py` | render + run pipeline + accumulate a `Report` scored vs ground truth |
| `report.py` | render the `Report` to markdown; inject it into the README markers |
| `cli.py` | `make eval` entry point (seed set or committed benchmark → tables; optional calibration) |
| `conformal.py` | conformal risk control for the agent verifier's threshold |

**Anti-circularity split (plan §7).** `ClaimGroundTruth.template_meta` carries per-file
template ids; the intended split trains on 5 hospital letterheads + 2 lab layouts and reports
on the unseen ones. The current harness reports over a seed spread; wiring the template
holdout as the *default* reported set — plus calibration (ECE) after temperature scaling — is
the remaining W8 work.

> Caveat: current numbers are on **digital** synthetic PDFs (real text layer, no OCR noise),
> so extraction is near-perfect. The synthetic-to-real gap (scanned/phone-photo docs through
> the OCR path) will be reported here openly, not hidden.
