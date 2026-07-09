"""M3 — Hybrid Extraction + M3.5 Value Grounding. See README.md."""

from pipeline.m3_extract.extract import extract_claim, extract_document
from pipeline.m3_extract.fuse import (
    apply_llm_fallback,
    fuse_field,
    llm_confidence,
)
from pipeline.m3_extract.grounding import ground_claim, ground_document, ground_field
from pipeline.m3_extract.llm_client import BudgetExceeded, LLMClient, MissingFixture

__all__ = [
    "extract_document",
    "extract_claim",
    "apply_llm_fallback",
    "fuse_field",
    "llm_confidence",
    "ground_claim",
    "ground_document",
    "ground_field",
    "LLMClient",
    "BudgetExceeded",
    "MissingFixture",
]
