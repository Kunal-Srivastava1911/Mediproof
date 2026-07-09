# Golden files — datagen

`claim_seed<N>.json` is the frozen ground-truth output of `sample_claim(seed=N)`. Tests
compare live output against these to catch any accidental change to the generator
(regressions fail CI, per CLAUDE.md).

Regenerate intentionally (after an approved generator change) with:

```
python -m datagen.regolden
```
