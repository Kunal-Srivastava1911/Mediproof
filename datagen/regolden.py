"""Regenerate committed golden ground-truth files.

Run deliberately after an *approved* change to the generator (CLAUDE.md rule 4 — golden
regressions fail CI, so regenerating is an explicit act, not automatic):

    python -m datagen.regolden
"""

from __future__ import annotations

from pathlib import Path

from datagen import sample_claim

GOLDEN_SEEDS = [42]
GOLDEN_DIR = Path(__file__).resolve().parents[1] / "tests" / "golden" / "datagen"


def main() -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for seed in GOLDEN_SEEDS:
        claim = sample_claim(seed=seed)
        out = GOLDEN_DIR / f"claim_seed{seed}.json"
        out.write_text(claim.model_dump_json(indent=2), encoding="utf-8")
        print(f"wrote {out.relative_to(GOLDEN_DIR.parents[2])}")


if __name__ == "__main__":
    main()
