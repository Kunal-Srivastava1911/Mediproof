# schemas/ — contracts (single source of truth)

Every module imports its types from here. **Do not modify a schema without an explicit,
human-approved task** (CLAUDE.md rule 1) — a contract change breaks every downstream module.

| File | Holds |
|------|-------|
| `common.py` | `DocType`, `Severity`, `BBox`/`Evidence`, `ExtractedField[T]`, confidence banding |
| `ground_truth.py` | *certain* datagen output: `HospitalBillGT`, `DischargeSummaryGT`, …, `ClaimGroundTruth`, `FaultLabel` |
| `documents.py` | *uncertain* extraction output: `ExtractedHospitalBill`, … (every field wrapped in `ExtractedField`) |
| `findings.py` | `Finding`, `FindingType`, `ProofQuote`, `FindingOrigin`, `FindingDecision` — audit review items |
| `claim.py` | `ClaimFile` — the runtime claim graph the API returns and the dashboard renders, incl. its `TimelineEvent`s, `EvidenceCell`s (the claim evidence graph) and `AuditMeta` |

### Agent findings are proof-carrying

A `Finding` raised by an LLM agent (`origin="agent"`) carries `proof`: verbatim quotes, each
located on its document's page (`grounded` + bbox `evidence`). It also records which checks
it passed (`verified_by`), its `verifier_score`, and `held_back=True` when it scored below the
calibrated threshold — held-back items are shown to reviewers only, never to the patient.
Reviewer decisions (`decision`, `decision_reason`) are logged as verifier training data.

`ground_truth.HELD_OUT_FAULTS` names the fault families the rule pack deliberately has no
rule for (the open-world eval split).

Key design choice: **ground truth is certain, extraction is uncertain.** Ground-truth
models hold plain typed values; extraction models wrap every field in `ExtractedField`
(value + confidence + bbox evidence + flags). `value=None, confidence=0` is the
well-defined "could not extract" state.

Run `make test-schemas`.
