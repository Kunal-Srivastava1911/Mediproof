# evals/ — evaluation harness

`make eval` renders a synthetic claim set, runs the full pipeline, scores it against ground
truth, and **writes the benchmark tables into the README** (between the `BENCHMARK` markers)
and `evals/RESULTS.md`. Everything is seed-driven, so the numbers reproduce exactly.

```bash
make eval            # or: ./run.ps1 eval  /  python -m evals.cli
```

## What it measures (plan §7)

- **Classification** — document-type accuracy of the P0 segmenter.
- **Field extraction** — exact-match and normalized-match (dates/amounts canonicalized) vs
  ground truth, overall and per document type.
- **Audit engine** — recall per fault type vs injected ground truth, and the
  **false-positive rate on clean files** (the number a buyer cares about most).
- **Coverage–accuracy curve** (headline) — accuracy of auto-accepted fields as a function of
  the % routed to human review, ordered by confidence.
- **Hybrid unit economics** — share of fields filled deterministically vs LLM calls made, and
  median latency; the "hybrid beats pure-LLM" argument.

## Files

| File | Role |
|------|------|
| `harness.py` | render + run pipeline + accumulate a `Report` scored vs ground truth |
| `report.py` | render the `Report` to markdown; inject it into the README markers |
| `cli.py` | `make eval` entry point (seed set → tables) |

**Anti-circularity split (plan §7).** `ClaimGroundTruth.template_meta` carries per-file
template ids; the intended split trains on 5 hospital letterheads + 2 lab layouts and reports
on the unseen ones. The current harness reports over a seed spread; wiring the template
holdout as the *default* reported set — plus calibration (ECE) after temperature scaling — is
the remaining W8 work.

> Caveat: current numbers are on **digital** synthetic PDFs (real text layer, no OCR noise),
> so extraction is near-perfect. The synthetic-to-real gap (scanned/phone-photo docs through
> the OCR path) will be reported here openly, not hidden.
