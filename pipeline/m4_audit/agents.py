"""M4 agent auditor: five specialist Claude agents + a skeptic, over one shared dossier.

The rule pack (`audit.py`) only finds what someone anticipated. The agents read the whole
file — including the discharge narrative — and *propose* review items. A proposal is never
shown as-is: it must be proof-carrying (verbatim quotes, located on the page by
`verify.py`), it is re-checked in code where it names dates or counts, and a skeptic agent
cross-examines it. `verify.py` turns what survives into `Finding`s.

All calls go through `LLMClient.complete_json` (record/replay, budget cap, structured
outputs). The dossier is the first content block of every specialist call and carries
`cache_control`, so the five calls share one cached prefix.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from pipeline.ir import ClaimIR
from pipeline.m3_extract.llm_client import LLMClient, quotes_found
from schemas.claim import DocumentRecord

AGENT_FINDING_TYPES = [
    "date_inconsistent", "temporal_inconsistency", "unsupported_by_documentation",
    "missing_report", "name_inconsistent", "age_gender_inconsistent",
    "cross_document_contradiction", "unmatched_medication", "bill_arithmetic_mismatch",
]
CHECK_KINDS = ["date_mismatch", "date_outside_window", "count_mismatch", "missing_document",
               "none"]

AGENT_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["findings"],
    "properties": {"findings": {"type": "array", "items": {
        "type": "object",
        "additionalProperties": False,
        "required": ["type", "severity", "title", "detail", "quotes", "check"],
        "properties": {
            "type": {"type": "string", "enum": AGENT_FINDING_TYPES},
            "severity": {"type": "string", "enum": ["info", "warning", "critical"]},
            "title": {"type": "string"},
            "detail": {"type": "string"},
            "quotes": {"type": "array", "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["document_id", "quote"],
                "properties": {"document_id": {"type": "string"}, "quote": {"type": "string"}},
            }},
            "check": {
                "type": "object",
                "additionalProperties": False,
                "required": ["kind", "values"],
                "properties": {
                    "kind": {"type": "string", "enum": CHECK_KINDS},
                    "values": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    }}},
}

def _combined_schema() -> dict:
    """AGENT_SCHEMA plus an `area` on each finding, for the one-call-covers-all mode."""
    schema = json.loads(json.dumps(AGENT_SCHEMA))
    item = schema["properties"]["findings"]["items"]
    item["properties"]["area"] = {"type": "string", "enum": list(AGENT_ROLES_KEYS)}
    item["required"] = ["area", *item["required"]]
    return schema


AGENT_ROLES_KEYS = ("billing", "clinical_record", "pharmacy", "timeline", "identity")

SKEPTIC_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reviews"],
    "properties": {"reviews": {"type": "array", "items": {
        "type": "object",
        "additionalProperties": False,
        # Reason first, then a two-word verdict: small models confuse a bare boolean.
        "required": ["index", "reason", "verdict"],
        "properties": {
            "index": {"type": "integer"},
            "reason": {"type": "string"},
            "verdict": {"type": "string", "enum": ["real_problem", "not_a_problem"]},
        },
    }}},
}

AUDITOR_SYSTEM = """\
You audit the documentation of an Indian health-insurance claim file before it is submitted.
This is documentation QA: you check that the documents are complete and agree with each
other. You never judge whether treatment was medically necessary, never decide coverage or
payment, and never describe anything as fraud. Every finding is a review item for a human.

How to report:
- Report only problems. Never report that something is consistent, correct or matches —
  if everything in your area agrees, return an empty list.
- The claim form's amount claimed is the hospital bill total plus the pharmacy bills; it is
  not expected to equal the hospital bill alone.
- Report only problems you can prove from the documents. Each finding needs at least one
  quote copied character-for-character from the document whose id you cite (at most 25
  words). For a contradiction, quote both sides, each with its own document id.
- When the problem is about dates or counts, fill `check` so it can be re-verified in code:
  date_mismatch with the two conflicting dates as YYYY-MM-DD; date_outside_window with
  [date, window_start, window_end] as YYYY-MM-DD; count_mismatch with the two conflicting
  numbers; missing_document with one keyword the missing report would contain. Convert
  relative dates such as "day 2 of admission" to calendar dates yourself. Otherwise use
  kind "none" with no values.
- Write the title and detail as neutral review items ("requires review", "differs",
  "not found in the file").
- Severity: critical when billed charges are contradicted by the documentation, warning for
  other inconsistencies, info for notes.
- Stay inside your area. If you find nothing there, return an empty list."""

AGENT_ROLES: dict[str, str] = {
    "billing": (
        "Your area: the hospital bill against the rest of the file. Billed room and ICU days "
        "should match the stay the discharge summary describes; every billed investigation "
        "or imaging study should have its report in the file; the claim form's amount "
        "claimed should match the bills."),
    "clinical_record": (
        "Your area: the discharge summary's narrative (Course in Hospital) against the bill "
        "and the reports. ICU and ward days, procedures and studies described in the "
        "narrative should agree with what was billed and reported."),
    "pharmacy": (
        "Your area: pharmacy bills against the prescriptions and the stay: medicines billed "
        "but never prescribed, and pharmacy bill dates relative to the stay and the "
        "discharge prescription."),
    "timeline": (
        "Your area: every date in the file. Place admission, discharge, ICU-to-ward "
        "transfer, tests, imaging, bills and prescriptions on one timeline, and report dates "
        "that disagree between documents or fall outside the stay."),
    "identity": (
        "Your area: the patient's identity across documents: name spelling, including "
        "one-letter variants, age, sex and IDs. Initials or abbreviations of the same name "
        "are not a problem; a different spelling of the name is."),
}

SKEPTIC_SYSTEM = """\
You are a skeptical second reviewer of proposed documentation review items for a health-
insurance claim file. For each proposed item, decide whether the documents really show the
problem. First write a one-sentence reason, then the verdict:
- "not_a_problem" when the quotes do not support it, when the difference is only formatting
  (12 Sep 2024 vs 12/09/2024), when it is an initial or abbreviation of the same name, when
  another document resolves it, when the item only says things are consistent, or when it
  asks for a clinical or coverage judgment rather than a documentation check;
- "real_problem" when the documents genuinely disagree or something billed or referenced
  is missing.
Count days carefully: "shifted to the ward on day N of admission" means N-1 days in ICU.
Return one review per proposed item, using its index."""


@dataclass
class Proposal:
    """One agent-proposed review item, before verification."""

    agent: str
    type: str
    severity: str
    title: str
    detail: str
    quotes: list[dict]
    check_kind: str
    check_values: list[str]
    skeptic: dict | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class AgentRun:
    proposals: list[Proposal] = field(default_factory=list)
    agents_run: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # human-readable reasons


_WATERMARK = "SPECIMEN — SYNTHETIC DATA"


def build_dossier(claim_ir: ClaimIR, records: list[DocumentRecord]) -> str:
    """Every document's id, type, pages and text — the agents' one shared view of the file."""
    by_page = {p.page: p for p in claim_ir.pages}
    parts = [f"Claim file {claim_ir.claim_id}: {len(records)} documents."]
    for rec in records:
        pages = [by_page[p] for p in rec.page_range if p in by_page]
        text = "\n".join(
            ln for p in pages for ln in p.text.splitlines() if _WATERMARK not in ln
        )
        page_list = ", ".join(str(p + 1) for p in rec.page_range)
        parts.append(f'<document id="{rec.document_id}" type="{rec.doc_type.value}" '
                     f'pages="{page_list}">\n{text}\n</document>')
    return "\n\n".join(parts)


def _content(dossier: str, instruction: str) -> list[dict]:
    return [
        {"type": "text", "text": dossier, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": instruction},
    ]


COMBINED_ROLE = (
    "Cover all five areas below and label each finding with its `area`.\n"
    + "\n".join(f"- {name}: {role}" for name, role in AGENT_ROLES.items())
)


def _collect(run: AgentRun, reply: dict, default_agent: str | None) -> None:
    for item in reply.get("findings", []):
        try:
            run.proposals.append(Proposal(
                agent=item.get("area") or default_agent, type=item["type"],
                severity=item["severity"], title=item["title"].strip(),
                detail=item["detail"].strip(),
                quotes=[q for q in item.get("quotes", []) if q.get("quote")],
                check_kind=item["check"]["kind"], check_values=item["check"]["values"],
            ))
        except (KeyError, TypeError, AttributeError):
            continue  # one malformed item never sinks the rest


def run_specialists(client: LLMClient, dossier: str) -> AgentRun:
    """Run the specialists over the dossier — one call each, or one combined call on free
    tiers (`client.agent_mode`). A failed call is skipped, never fatal; an exhausted quota
    stops further calls."""
    run = AgentRun()
    if getattr(client, "agent_mode", "separate") == "combined":
        try:
            reply = client.complete_json(AUDITOR_SYSTEM, _content(dossier, COMBINED_ROLE),
                                         _combined_schema(),
                                         accept=lambda r: quotes_found(r, dossier))
        except Exception as exc:  # noqa: BLE001
            run.skipped.append(f"combined: {type(exc).__name__}: {str(exc)[:160]}")
            return run
        run.agents_run = list(AGENT_ROLES)
        _collect(run, reply, None)
        return run
    for name, role in AGENT_ROLES.items():
        if getattr(client, "quota_exhausted", False):
            run.skipped.append(f"{name}: quota exhausted")
            continue
        try:
            reply = client.complete_json(AUDITOR_SYSTEM, _content(dossier, role), AGENT_SCHEMA,
                                         accept=lambda r: quotes_found(r, dossier))
        except Exception as exc:  # noqa: BLE001 - replay miss, budget, API error, bad JSON
            run.skipped.append(f"{name}: {type(exc).__name__}: {str(exc)[:160]}")
            continue
        run.agents_run.append(name)
        _collect(run, reply, name)
    return run


def run_skeptic(client: LLMClient, dossier: str, proposals: list[Proposal]) -> bool:
    """Ask the skeptic to cross-examine every proposal (in place). False if it couldn't run."""
    if not proposals:
        return True
    if getattr(client, "quota_exhausted", False):
        return False
    listing = json.dumps([
        {"index": i, "agent": p.agent, "type": p.type, "title": p.title, "detail": p.detail,
         "quotes": p.quotes, "check": {"kind": p.check_kind, "values": p.check_values}}
        for i, p in enumerate(proposals)
    ], ensure_ascii=False, indent=1)
    content = [
        {"type": "text", "text": dossier, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": f"Proposed review items:\n{listing}"},
    ]
    try:
        reply = client.complete_json(SKEPTIC_SYSTEM, content, SKEPTIC_SCHEMA)
    except Exception:  # noqa: BLE001
        return False
    for review in reply.get("reviews", []):
        i = review.get("index")
        if isinstance(i, int) and 0 <= i < len(proposals):
            upheld = review.get("verdict") == "real_problem" if "verdict" in review \
                else bool(review.get("upheld"))
            proposals[i].skeptic = {"upheld": upheld,
                                    "reason": str(review.get("reason", "")).strip()}
    return True
