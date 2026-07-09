"""M4 — Cross-Document Audit Engine. See README.md."""

from pipeline.m4_audit.audit import RuleHit, load_rules, run_audit

__all__ = ["run_audit", "load_rules", "RuleHit"]
