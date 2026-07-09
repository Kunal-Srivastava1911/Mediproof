from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = REPO_ROOT / "tests" / "golden"


@pytest.fixture(scope="session")
def golden_dir() -> Path:
    return GOLDEN_DIR


@pytest.fixture(scope="session")
def render_claim_factory(tmp_path_factory):
    """Render a claim (optionally with a forced fault) to a temp dir, once per (seed, fault).

    Pipeline tests need a *real* claim PDF to ingest. Rendering is seeded, so this stays
    deterministic; it's cached per (seed, fault) so Chromium launches at most once per case.
    Tests that use it should be marked `slow` (they launch headless Chromium).
    """
    from datagen import inject_fault, sample_claim
    from datagen.render import render_claim
    from schemas.ground_truth import FaultType

    cache: dict[tuple[int, str | None], SimpleNamespace] = {}

    def _factory(seed: int = 42, fault: str | None = None) -> SimpleNamespace:
        key = (seed, fault)
        if key not in cache:
            claim = sample_claim(seed=seed)
            if fault:
                inject_fault(claim, seed=seed, fault_type=FaultType(fault))
            out = tmp_path_factory.mktemp(f"claim_{seed}_{fault or 'clean'}")
            manifest = render_claim(claim, out)
            cache[key] = SimpleNamespace(
                dir=out, claim=claim, manifest=manifest, merged=out / "claim.pdf",
            )
        return cache[key]

    return _factory


@pytest.fixture(scope="session")
def rendered_claim(render_claim_factory) -> SimpleNamespace:
    """A clean seed-42 claim rendered to PDFs (merged + per-doc) with its ground truth."""
    return render_claim_factory(42)
