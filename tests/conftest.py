from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = REPO_ROOT / "tests" / "golden"


@pytest.fixture(scope="session")
def golden_dir() -> Path:
    return GOLDEN_DIR
