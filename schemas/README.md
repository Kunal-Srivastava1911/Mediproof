# schemas/ — contracts (single source of truth)

Every module imports its types from here. **Do not modify a schema without an explicit,
human-approved task** (CLAUDE.md rule 1) — a contract change breaks every downstream module.

| File | Holds |
|------|-------|
| `common.py` | `DocType`, `Severity`, `BBox`/`Evidence`, `ExtractedField[T]`, confidence banding |
| `ground_truth.py` | *certain* datagen output: `HospitalBillGT`, `DischargeSummaryGT`, …, `ClaimGroundTruth`, `FaultLabel` |
| `documents.py` | *uncertain* extraction output: `ExtractedHospitalBill`, … (every field wrapped in `ExtractedField`) |
| `findings.py` | `Finding`, `FindingType`, `Severity` — audit review items |
| `claim.py` | `ClaimFile` — the runtime claim graph the API returns and the dashboard renders |

Key design choice: **ground truth is certain, extraction is uncertain.** Ground-truth
models hold plain typed values; extraction models wrap every field in `ExtractedField`
(value + confidence + bbox evidence + flags). `value=None, confidence=0` is the
well-defined "could not extract" state.

Run `make test-schemas`.
