# datagen/ — MediClaim-Bench synthetic generator

Turns a **seed** into a coherent synthetic claim file: a set of PDFs plus a ground-truth
JSON answer key. Fully deterministic — the same seed reproduces byte-identical ground truth
(CLAUDE.md rule 6).

## Commands

```bash
make datagen-sample                          # one claim -> data/sample/  (W1 DoD)
python -m datagen.cli bulk --count 300       # the benchmark set -> data/bench/
python -m datagen.regolden                   # regenerate committed golden files (deliberate)
```

## Layout

| File | Role |
|------|------|
| `fake_data.py` | fictional hospitals/labs/pharmacies, generic drugs, ICD-10, charge structures, clinical scenarios |
| `sampler.py` | seed → one coherent `ClaimGroundTruth` (patient consistent, dates ordered, bill arithmetic exact) |
| `templates/` | Jinja HTML + CSS letterheads (bill · discharge · pharmacy) rendered to A4 |
| `render.py` | HTML → PDF via headless Chromium (Playwright); merges per-doc PDFs into `claim.pdf` |
| `cli.py` | `sample` / `bulk` entry points |

## Coherence guarantees (a *clean* file)

- one canonical patient on every document
- `admission_date < discharge_date`; pharmacy dates within the admission window
- bill line items sum exactly to subtotal/total
- drugs, procedures and labs all drawn from one clinical scenario

## Safety

Every institution is fictional; every page carries a `SPECIMEN — SYNTHETIC DATA`
watermark whose region is masked out of OCR evaluation (plan §5).

## Done (W1) / Next (W2)

- ✅ bill, discharge, pharmacy templates; deterministic sampler; merged claim PDF; golden tests
- ⬜ lab + prescription + claim-form + ID templates; Augraphy degradation; **fault injection**
  (`faults.py` — the `FaultLabel` contract is already defined in `schemas/`)

Run `make test-datagen`.
