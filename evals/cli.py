"""`make eval` entry point: render an eval set, score it, write README + RESULTS tables.

    python -m evals.cli --out data/bench_eval

Uses an unseen-template-friendly seed set (plan §7): clean claims across a spread of seeds
plus one claim per fault type, all rendered on the fly and reproducible.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from evals.harness import build_and_score
from evals.report import update_readme, write_results
from schemas.ground_truth import FaultType

# One faulty claim per fault type (seed chosen so the fault applies), plus a clean spread.
_FAULTY = {200 + i: f.value for i, f in enumerate(FaultType)}
_CLEAN = list(range(300, 316))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="evals", description="MediProof eval harness")
    parser.add_argument("--out", default="data/bench_eval")
    parser.add_argument("--readme", default="README.md")
    parser.add_argument("--results", default="evals/RESULTS.md")
    parser.add_argument("--clean", type=int, default=len(_CLEAN),
                        help="number of clean claims to evaluate")
    args = parser.parse_args(argv)

    clean = _CLEAN[: args.clean]
    print(f"[eval] rendering + scoring {len(clean)} clean + {len(_FAULTY)} faulty claims...")
    report = build_and_score(clean, _FAULTY, Path(args.out))

    write_results(report, args.results)
    updated = update_readme(report, args.readme)
    print(f"[eval] wrote {args.results}"
          + (f" and updated {args.readme}" if updated else f" (no markers in {args.readme})"))
    print(f"[eval] classification {report.classification_correct}/{report.classification_total}, "
          f"clean-file false positives: {report.clean_false_positives}")


if __name__ == "__main__":
    main()
