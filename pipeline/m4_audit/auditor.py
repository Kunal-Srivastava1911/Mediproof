"""Entry point for the agent auditor: dossier → specialists → skeptic → verifier."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from pipeline.ir import ClaimIR
from pipeline.m3_extract.llm_client import LLMClient
from pipeline.m4_audit.agents import build_dossier, run_skeptic, run_specialists
from pipeline.m4_audit.verify import load_threshold, verify
from schemas.claim import AuditMeta, DocumentRecord
from schemas.findings import Finding


@dataclass
class AgentAuditResult:
    findings: list[Finding] = field(default_factory=list)
    meta: AuditMeta = field(default_factory=AuditMeta)


def agents_enabled() -> bool:
    return os.getenv("LLM_AGENTS", "1") != "0"


def run_agent_audit(
    claim_ir: ClaimIR,
    records: list[DocumentRecord],
    rule_findings: list[Finding],
    client: LLMClient,
) -> AgentAuditResult:
    """Run the agent auditor. Never raises: anything that can't run is reported in `meta`."""
    threshold = load_threshold()
    result = AgentAuditResult(meta=AuditMeta(verifier_threshold=threshold))
    if not agents_enabled():
        result.meta.note = "Agent auditor disabled (LLM_AGENTS=0)."
        return result

    calls0, spent0 = client.calls, client.spent_usd
    dossier = build_dossier(claim_ir, records)
    run = run_specialists(client, dossier)
    result.meta.agents_run = run.agents_run
    if not run.agents_run:
        result.meta.note = (
            "Agent auditor skipped: no recorded Claude responses for this file and live calls "
            "are off. Set ANTHROPIC_API_KEY and LLM_LIVE=1 to run it." if not client.live
            else f"Agent auditor could not run ({'; '.join(run.skipped)}).")
        return result

    skeptic_ran = run_skeptic(client, dossier, run.proposals)
    result.findings = verify(run.proposals, claim_ir, records, rule_findings,
                             threshold=threshold, skeptic_ran=skeptic_ran)
    if run.skipped:
        result.meta.note = f"Some agents did not run: {'; '.join(run.skipped)}."
    elif not skeptic_ran and run.proposals:
        result.meta.note = "Skeptic agent did not run; scores treat its verdict as neutral."
    result.meta.llm_calls = client.calls - calls0
    result.meta.llm_cost_usd = round(client.spent_usd - spent0, 6)
    return result
