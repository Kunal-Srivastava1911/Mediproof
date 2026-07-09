# M5 — Completeness Checker

**In:** the segmented documents (`list[DocumentRecord]`) + the `claim_type`. **Out:** a
`CompletenessReport` (`required` / `present` / `missing` doc types).

Maps each claim type to its required-document checklist (`checklists.yaml`) and emits the
present/missing matrix. Config-driven: adding a claim type is a data change, not code.

```python
from pipeline.m5_complete import complete_claim
report = complete_claim("cashless_hospitalization", records)
# report.missing == [] for a complete claim; [DocType.lab_report] if labs are absent
```

A missing required document is complementary to M4's cross-document rules — e.g. the
`missing_lab_report` fault shows up both as an M4 review item *and* here in the matrix.

**DoD:** present/missing matrix produced for the sample claim; a missing-doc fault is caught.
Run `make test-m5`.
