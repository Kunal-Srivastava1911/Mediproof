"""M3 — Hybrid Extraction + M3.5 Value Grounding. See README.md."""

from pipeline.m3_extract.extract import extract_claim, extract_document

__all__ = ["extract_document", "extract_claim"]
