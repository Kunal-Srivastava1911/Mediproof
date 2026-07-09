"""M2 — Segmentation + Classification. See README.md."""

from pipeline.m2_segment.segment import DOC_KEYWORDS, classify_page, segment_claim

__all__ = ["classify_page", "segment_claim", "DOC_KEYWORDS"]
