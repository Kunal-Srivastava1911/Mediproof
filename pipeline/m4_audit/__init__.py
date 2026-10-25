"""M4 — Cross-Document Audit Engine: rule pack + agent auditor. See README.md."""

from pipeline.m4_audit.audit import RuleHit, load_rules, run_audit
from pipeline.m4_audit.auditor import AgentAuditResult, run_agent_audit
from pipeline.m4_audit.timeline import build_evidence_map, build_timeline

__all__ = [
    "run_audit", "load_rules", "RuleHit", "run_agent_audit", "AgentAuditResult",
    "build_timeline", "build_evidence_map",
]
