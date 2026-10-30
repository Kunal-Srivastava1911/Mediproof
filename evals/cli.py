"""`make eval` entry point: render an eval set, score it, write README + RESULTS tables.

    python -m evals.cli --out data/bench_eval
    python -m evals.cli --bench bench/mediclaim-bench-v2 --limit 60      # committed benchmark
    python -m evals.cli --calibrate 20 --alpha 0.1                        # + conformal threshold

Default set: a clean spread plus, for every fault family, a claim where that family's recipe
genuinely applies (held-out families need an ICU stay / an imaging study). Everything is
rendered on the fly from seeds and reproduces exactly.

The agent auditor runs on replayed fixtures, or live when LLM_LIVE=1 (one shared client, so
LLM_BUDGET_USD caps the whole run). Calibration uses its *own* clean claims (seeds 400+),
never the evaluated ones, then writes pipeline/m4_audit/calibration.json before the eval.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datagen import inject_fault, sample_claim
from evals.conformal import crc_threshold, write_calibration
from evals.harness import build_and_score
from evals.report import update_readme, write_results
from pipeline.m3_extract.llm_client import LLMClient
from pipeline.m4_audit.verify import CALIBRATION_PATH
from schemas.ground_truth import FaultType

_CLEAN = list(range(300, 316))
_CALIBRATION_START = 400


def faulty_plan(per_type: int = 1, start: int = 200) -> list[tuple[int, str]]:
    """For each fault family, the first `per_type` seeds (from `start`) where it applies."""
    plan: list[tuple[int, str]] = []
    for ft in FaultType:
        seed, found = start, 0
        while found < per_type:
            claim = sample_claim(seed=seed)
            inject_fault(claim, seed=seed, fault_type=ft)
            if claim.faults[0].fault_type is ft:
                plan.append((seed, ft.value))
                found += 1
            seed += 1
    return plan


def bench_plan(bench_dir: Path, limit: int | None) -> tuple[list[int], list[tuple[int, str]]]:
    index = json.loads((bench_dir / "index.json").read_text(encoding="utf-8"))
    if limit:
        index = index[:limit]
    clean = [row["seed"] for row in index if not row["faults"]]
    faulty = [(row["seed"], row["faults"][0]) for row in index if row["faults"]]
    return clean, faulty


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="evals", description="MediProof eval harness")
    parser.add_argument("--out", default="data/bench_eval")
    parser.add_argument("--readme", default="README.md")
    parser.add_argument("--results", default="evals/RESULTS.md")
    parser.add_argument("--clean", type=int, default=len(_CLEAN),
                        help="number of clean claims to evaluate (default set)")
    parser.add_argument("--per-fault", type=int, default=1,
                        help="faulty claims per fault family (default set)")
    parser.add_argument("--bench", type=Path, default=None,
                        help="evaluate a committed benchmark (dir with index.json) instead")
    parser.add_argument("--limit", type=int, default=None, help="first N benchmark claims")
    parser.add_argument("--calibrate", type=int, default=0,
                        help="calibrate the verifier threshold on N separate clean claims first")
    parser.add_argument("--alpha", type=float, default=0.1,
                        help="target: P(clean claim shows >= 1 agent item) <= alpha")
    args = parser.parse_args(argv)

    client = LLMClient(race=False)  # published numbers stay single-model
    if args.calibrate:
        seeds = list(range(_CALIBRATION_START, _CALIBRATION_START + args.calibrate))
        print(f"[eval] calibrating on {len(seeds)} clean claims (alpha={args.alpha})...")
        cal = build_and_score(seeds, [], Path(args.out) / "calibration", llm_client=client)
        cert = crc_threshold(cal.clean_agent_scores, args.alpha)
        if cert["feasible"]:
            write_calibration(cert, CALIBRATION_PATH)
            print(f"[eval] threshold {cert['threshold']} (empirical risk "
                  f"{cert['empirical_risk']}, bound {cert['risk_bound']}) -> {CALIBRATION_PATH}")
        else:
            print(f"[eval] calibration not written: {cert['reason']}")

    if args.bench:
        clean, faulty = bench_plan(args.bench, args.limit)
    else:
        clean, faulty = _CLEAN[: args.clean], faulty_plan(args.per_fault)
    print(f"[eval] rendering + scoring {len(clean)} clean + {len(faulty)} faulty claims...")
    report = build_and_score(clean, faulty, Path(args.out), llm_client=client)

    write_results(report, args.results)
    updated = update_readme(report, args.readme)
    print(f"[eval] wrote {args.results}"
          + (f" and updated {args.readme}" if updated else f" (no markers in {args.readme})"))
    print(f"[eval] classification {report.classification_correct}/{report.classification_total}, "
          f"clean-file severe items shown: {report.clean_false_positives}, "
          f"agent auditor ran on {report.agent_claims}/{report.n_claims} claims, "
          f"live spend ${client.spent_usd:.2f}")


if __name__ == "__main__":
    main()
