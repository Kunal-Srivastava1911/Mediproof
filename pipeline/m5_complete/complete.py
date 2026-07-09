"""M5 — Completeness Checker (plan §M5).

Maps a claim type to its required document checklist and reports the present/missing matrix.
Config-driven (`checklists.yaml`): adding a claim type is a data change, not a code change.
A missing required document also surfaces as a `missing_document` review item for the audit
report, complementary to M4's cross-document rules.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from schemas.claim import CompletenessReport, DocumentRecord
from schemas.common import DocType

_CHECKLIST_PATH = Path(__file__).parent / "checklists.yaml"


def load_checklists(path: str | Path | None = None) -> dict:
    return yaml.safe_load(Path(path or _CHECKLIST_PATH).read_text(encoding="utf-8"))


def required_for(claim_type: str, checklists: dict | None = None) -> list[DocType]:
    cfg = checklists or load_checklists()
    entry = cfg.get("claim_types", {}).get(claim_type) or cfg.get("default", {})
    return [DocType(d) for d in entry.get("required", [])]


def check_completeness(
    claim_type: str,
    present: list[DocType],
    checklists: dict | None = None,
) -> CompletenessReport:
    """Build the required/present/missing matrix for a claim (plan §M5)."""
    required = required_for(claim_type, checklists)
    present_set = set(present)
    return CompletenessReport(
        claim_type=claim_type,
        required=required,
        present=[d for d in required if d in present_set],
        missing=[d for d in required if d not in present_set],
    )


def complete_claim(
    claim_type: str,
    records: list[DocumentRecord],
    checklists: dict | None = None,
) -> CompletenessReport:
    """Completeness report from the segmented documents of a claim."""
    present = [r.doc_type for r in records if r.doc_type != DocType.other]
    return check_completeness(claim_type, present, checklists)
