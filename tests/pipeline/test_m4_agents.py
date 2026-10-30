"""Agent auditor: proof-carrying verification over a real rendered claim, offline.

A fake client stands in for Claude (record/replay fixtures are the production path); the
replies are canned so these tests pin the *verifier's* behaviour: grounding gates
everything, code checks and the skeptic move the score, ungrounded or refuted proposals are
held back, and an agent repeating a rule finding corroborates it instead of duplicating it.
"""

import pytest

from pipeline.m1_ingest import ingest_pdf
from pipeline.m2_segment import segment_claim
from pipeline.m3_extract import extract_claim, ground_claim
from pipeline.m3_extract.llm_client import LLMClient
from pipeline.m4_audit import build_evidence_map, build_timeline, run_agent_audit, run_audit
from pipeline.m4_audit.agents import AGENT_ROLES, SKEPTIC_SYSTEM, Proposal
from pipeline.m4_audit.verify import code_check, score
from schemas.common import DocType
from schemas.findings import FindingOrigin, FindingType

# ---------------------------------------------------------------- pure units (fast)


def _p(kind, values, quotes=()):
    return Proposal(agent="timeline", type="date_inconsistent", severity="warning", title="t",
                    detail="d", quotes=list(quotes), check_kind=kind, check_values=values)


def test_code_checks_confirm_and_refute():
    assert code_check(_p("date_mismatch", ["2024-09-09", "2024-09-12"]), {}) is True
    assert code_check(_p("date_mismatch", ["2024-09-09", "2024-09-09"]), {}) is False
    assert code_check(_p("date_outside_window",
                         ["2024-09-20", "2024-09-09", "2024-09-12"]), {}) is True
    assert code_check(_p("count_mismatch", ["3 days", "1"]), {}) is True
    assert code_check(_p("count_mismatch", ["2", "2.0"]), {}) is False
    assert code_check(_p("none", []), {}) is None
    texts = {"BILL": "ct chest 4500.00", "RAD": "radiology report ct chest impression"}
    missing = _p("missing_document", ["CT Chest"], [{"document_id": "BILL", "quote": "x"}])
    assert code_check(missing, texts) is False          # the report is actually there
    assert code_check(missing, {"BILL": texts["BILL"]}) is True


def test_score_gates_on_grounding():
    assert score(False, True, True) == 0.0
    assert score(True, True, True) == 1.0
    assert score(True, None, None) == 0.55
    assert score(True, False, True) < score(True, True, True)


# ---------------------------------------------------------------- over a rendered claim (slow)


class _FakeClaude(LLMClient):
    """Returns canned replies keyed by which agent is asking."""

    def __init__(self, replies, tmp_path):
        super().__init__(tmp_path, live=False)
        self.replies = replies

    def complete_json(self, system, content, schema, *, key=None, max_tokens=16000,
                      accept=None):
        self.calls += 1
        if system == SKEPTIC_SYSTEM:
            return self.replies.get("skeptic", {"reviews": []})
        role = content[-1]["text"]
        name = next(n for n, r in AGENT_ROLES.items() if r == role)
        return self.replies.get(name, {"findings": []})


@pytest.fixture(scope="module")
def icu_claim(render_claim_factory):
    rc = render_claim_factory(5, "icu_days_mismatch")  # seed 5 = pneumonia (ICU stay)
    ir = ingest_pdf(rc.merged, claim_id=rc.claim.claim_id)
    recs = ground_claim(ir, extract_claim(ir, segment_claim(ir)))
    return rc, ir, recs


def _doc(recs, doc_type):
    return next(r.document_id for r in recs if r.doc_type == doc_type)


@pytest.mark.slow
def test_icu_days_mismatch_is_proved_and_shown(icu_claim, tmp_path):
    rc, ir, recs = icu_claim
    bill, disch = _doc(recs, DocType.hospital_bill), _doc(recs, DocType.discharge_summary)
    icu_billed = next(i for i in next(d for d in rc.claim.documents
                                      if d.doc_type == DocType.hospital_bill).line_items
                      if i.description == "ICU Charges").quantity
    replies = {
        "clinical_record": {"findings": [{
            "type": "unsupported_by_documentation", "severity": "critical",
            "title": "ICU days billed differ from the discharge summary",
            "detail": f"The bill charges {int(icu_billed)} ICU days; the narrative moves the "
                      "patient to the ward on day 2; requires review.",
            "quotes": [{"document_id": bill, "quote": "ICU Charges"},
                       {"document_id": disch,
                        "quote": "Shifted to the ward on day 2 of admission"}],
            "check": {"kind": "count_mismatch", "values": [str(int(icu_billed)), "1"]},
        }]},
        "identity": {"findings": [{
            "type": "name_inconsistent", "severity": "warning", "title": "Name differs",
            "detail": "A name differs; requires review.",
            "quotes": [{"document_id": bill, "quote": "Patient Name Someone Entirely Else"}],
            "check": {"kind": "none", "values": []},
        }]},
        "skeptic": {"reviews": [{"index": 0, "upheld": True, "reason": "Quotes conflict."},
                                {"index": 1, "upheld": False, "reason": "Not in the file."}]},
    }
    rules = run_audit(recs)
    result = run_agent_audit(ir, recs, rules, _FakeClaude(replies, tmp_path))

    shown = [f for f in result.findings if not f.held_back]
    held = [f for f in result.findings if f.held_back]
    assert len(shown) == 1 and len(held) == 1
    icu = shown[0]
    assert icu.type is FindingType.unsupported_by_documentation
    assert icu.origin is FindingOrigin.agent and icu.agent == "Clinical-record agent"
    assert set(icu.verified_by) == {"grounding", "code check", "skeptic agent"}
    assert icu.verifier_score == 1.0
    assert all(q.grounded for q in icu.proof) and icu.evidence   # clickable on the page
    assert set(icu.document_ids) == {bill, disch}
    assert held[0].verifier_score == 0.0                           # hallucinated quote
    assert result.meta.agents_run == list(AGENT_ROLES)

    findings = rules + result.findings
    timeline = build_timeline(recs, findings)
    assert any(ev.conflict and icu.id in ev.finding_ids for ev in timeline)
    assert build_evidence_map(recs, findings)


@pytest.mark.slow
def test_agent_repeating_a_rule_corroborates_it(render_claim_factory, tmp_path):
    rc = render_claim_factory(42, "claim_form_date_mismatch")
    ir = ingest_pdf(rc.merged, claim_id=rc.claim.claim_id)
    recs = ground_claim(ir, extract_claim(ir, segment_claim(ir)))
    form, bill = _doc(recs, DocType.claim_form), _doc(recs, DocType.hospital_bill)
    cf = next(d for d in rc.claim.documents if d.doc_type == DocType.claim_form)
    b = next(d for d in rc.claim.documents if d.doc_type == DocType.hospital_bill)
    replies = {"timeline": {"findings": [{
        "type": "date_inconsistent", "severity": "warning", "title": "Admission date differs",
        "detail": "Claim form and bill disagree; requires review.",
        "quotes": [{"document_id": form,
                    "quote": f"Date of Admission {cf.admission_date:%d/%m/%Y}"},
                   {"document_id": bill,
                    "quote": f"Admission Date {b.admission_date:%d %b %Y}"}],
        "check": {"kind": "date_mismatch",
                  "values": [cf.admission_date.isoformat(), b.admission_date.isoformat()]},
    }]}, "skeptic": {"reviews": [{"index": 0, "upheld": True, "reason": "Dates differ."}]}}
    rules = run_audit(recs)
    result = run_agent_audit(ir, recs, rules, _FakeClaude(replies, tmp_path))
    assert result.findings == []                     # folded into the rule finding
    rule = next(f for f in rules if f.rule_id == "claim_form_dates")
    assert "Timeline agent (agreed)" in rule.verified_by


def test_combined_mode_is_one_call_and_keeps_areas(tmp_path):
    from pipeline.m4_audit.agents import run_specialists

    class _OneCall(LLMClient):
        def complete_json(self, system, content, schema, *, key=None, max_tokens=16000,
                          accept=None):
            self.calls += 1
            assert "area" in schema["properties"]["findings"]["items"]["required"]
            return {"findings": [{"area": "timeline", "type": "date_inconsistent",
                                  "severity": "warning", "title": "t", "detail": "d",
                                  "quotes": [{"document_id": "D", "quote": "q"}],
                                  "check": {"kind": "none", "values": []}}]}

    client = _OneCall(tmp_path, live=False)
    client.agent_mode = "combined"
    run = run_specialists(client, "dossier")
    assert client.calls == 1 and run.agents_run == list(AGENT_ROLES)
    assert [p.agent for p in run.proposals] == ["timeline"]


def test_exhausted_quota_stops_further_agent_calls(tmp_path):
    from pipeline.m4_audit.agents import run_specialists

    class _Exhausted(LLMClient):
        def complete_json(self, *a, **k):
            self.calls += 1
            self.quota_exhausted = True
            raise RuntimeError("429")

    client = _Exhausted(tmp_path, live=False)
    client.agent_mode = "separate"
    run = run_specialists(client, "dossier")
    assert client.calls == 1 and not run.agents_run
    assert sum("quota exhausted" in s for s in run.skipped) == 4


@pytest.mark.slow
def test_no_fixtures_means_rules_only_with_a_note(icu_claim, tmp_path):
    rc, ir, recs = icu_claim
    result = run_agent_audit(ir, recs, run_audit(recs), LLMClient(tmp_path, live=False))
    assert result.findings == []
    assert "no recorded AI responses" in result.meta.note
