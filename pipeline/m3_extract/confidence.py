"""Per-field confidence — the fusion scheme from plan §M3.

Every extracted field carries `confidence ∈ [0,1]` that decides its review band
(green ≥ 0.8 auto-accept, amber 0.5–0.8, red < 0.5). This module is the single place those
numbers are defined, shared by the deterministic layer (`extract.py`) and the LLM
fallback + fusion (`fuse.py`).
"""

from __future__ import annotations

from schemas.common import ExtractedField, FieldSource

# Deterministic layer (plan §M3): rule + validator pass -> 0.95 base, scaled by mean OCR
# word confidence of the source tokens (1.0 for a digital text layer).
RULE_VALIDATED = 0.95
RULE_UNVALIDATED = 0.85

# LLM fallback self-consistency (k=3): agreement 3/3 -> 0.85, 2/3 -> 0.60, else 0.30.
LLM_AGREE_FULL = 0.85
LLM_AGREE_PARTIAL = 0.60
LLM_AGREE_NONE = 0.30
VALIDATOR_BONUS = 0.10   # a passing validator adds this (capped at 1.0)
CONFLICT_CONFIDENCE = 0.25  # rule and LLM disagree -> low + auto-flag for HITL


def _round(x: float) -> float:
    return round(min(1.0, max(0.0, x)), 4)


def rule_field(value, *, validated: bool = False, source_conf: float = 1.0) -> ExtractedField:
    """Build an `ExtractedField` from the deterministic layer (grounding added later by M3.5)."""
    base = RULE_VALIDATED if validated else RULE_UNVALIDATED
    return ExtractedField(value=value, confidence=_round(base * source_conf),
                          source=FieldSource.rule)


def missing_field() -> ExtractedField:
    """The well-defined 'could not extract' state: value=None, confidence=0."""
    return ExtractedField()
