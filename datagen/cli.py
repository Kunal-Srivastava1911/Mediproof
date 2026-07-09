"""datagen command-line entry.

    python -m datagen.cli sample --seed 42 --out data/sample
    python -m datagen.cli bulk   --count 300 --out data/bench --start-seed 1000

`sample` is the W1 DoD target (`make datagen-sample`): render doc types to PDF with a
ground-truth JSON answer key.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datagen.render import render_claim
from datagen.sampler import sample_claim


def _cmd_sample(args: argparse.Namespace) -> None:
    claim = sample_claim(seed=args.seed)
    manifest = render_claim(claim, Path(args.out))
    print(json.dumps(manifest, indent=2))
    print(f"\n[datagen] claim {claim.claim_id}: "
          f"rendered {len(manifest['doc_types_rendered'])} doc types "
          f"-> {Path(args.out).resolve()}")


def _cmd_bulk(args: argparse.Namespace) -> None:
    out_root = Path(args.out)
    index: list[dict] = []
    for i in range(args.count):
        seed = args.start_seed + i
        claim = sample_claim(seed=seed)
        render_claim(claim, out_root / claim.claim_id)
        index.append({"claim_id": claim.claim_id, "seed": seed,
                      "template_meta": claim.template_meta,
                      "faults": [f.fault_type.value for f in claim.faults]})
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    print(f"[datagen] generated {args.count} claims -> {out_root.resolve()}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="datagen", description="MediClaim-Bench generator")
    sub = parser.add_subparsers(required=True)

    p_sample = sub.add_parser("sample", help="render one sample claim")
    p_sample.add_argument("--seed", type=int, default=42)
    p_sample.add_argument("--out", default="data/sample")
    p_sample.set_defaults(func=_cmd_sample)

    p_bulk = sub.add_parser("bulk", help="render many claims")
    p_bulk.add_argument("--count", type=int, default=300)
    p_bulk.add_argument("--start-seed", type=int, default=1000)
    p_bulk.add_argument("--out", default="data/bench")
    p_bulk.set_defaults(func=_cmd_bulk)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
