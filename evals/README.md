# evals/ — evaluation harness

`make eval` runs this CLI and regenerates the README benchmark tables.

**Anti-circularity split (by template, not by file):** train/tune on 5 hospital letterheads
+ 2 lab layouts; evaluate on 3 unseen letterheads + 1 unseen lab layout + the local real
redacted set. Splits are seed-fixed and committed; reported numbers come from unseen
templates only. `ClaimGroundTruth.template_meta` carries the per-file template ids the split
enforcer keys on.

**Metrics**
- Classification accuracy + confusion matrix; segmentation boundary F1.
- Field extraction: exact-match and normalized-match (dates/amounts/units canonicalized)
  P/R/F1 per doc type; ANLS for free-text.
- Audit engine: precision/recall per fault type vs injected ground truth; **false-positive
  rate on clean files**.
- **Coverage–accuracy curve** (headline): accuracy of auto-accepted fields vs % sent to
  human review, ordered by confidence. Plus calibration (ECE) after temperature scaling.
- Cost & latency: per-page token accounting on every LLM call; hybrid vs pure-LLM table.

Lands W3+ (starts with classification/segmentation once M2 exists).
