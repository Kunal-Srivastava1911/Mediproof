"""M3 LLM fallback: record/replay client, self-consistency, fusion, hybrid routing."""

import json
from datetime import date

import pytest

from pipeline.m3_extract.confidence import rule_field
from pipeline.m3_extract.fuse import (
    _fallback_key,
    apply_llm_fallback,
    fill_field,
    fuse_field,
    llm_confidence,
    parse_date,
    parse_str,
)
from pipeline.m3_extract.llm_client import BudgetExceeded, LLMClient, MissingFixture
from schemas.common import DocType, ExtractedField, FieldSource
from schemas.documents import ExtractedHospitalBill


class _FakeLiveClient(LLMClient):
    """A client whose 'provider' returns canned text — for exercising the live/record path."""

    def _call_provider(self, prompt: str) -> str:
        return json.dumps({"samples": ["Recorded Value"] * 3})


def _write(dirpath, key, payload):
    (dirpath / f"{key}.json").write_text(json.dumps(payload), encoding="utf-8")


# ----------------------------------------------------------------- confidence + fusion

def test_llm_confidence_bands():
    assert llm_confidence(3, 3) == 0.85
    assert llm_confidence(2, 3) == 0.60
    assert llm_confidence(1, 3) == 0.30
    assert llm_confidence(3, 3, validated=True) == pytest.approx(0.95)
    assert llm_confidence(3, 3, validated=False) == 0.30  # failed validator forces low


def test_fuse_agreement_boosts_and_conflict_flags():
    rule = rule_field("Advik Maharaj")              # 0.85 rule
    llm_same = ExtractedField(value="advik maharaj", confidence=0.85, source=FieldSource.llm)
    fused = fuse_field(rule, llm_same)
    assert fused.source == FieldSource.fusion
    assert fused.confidence == pytest.approx(0.90)   # max+0.05, case-insensitive match

    llm_diff = ExtractedField(value="Someone Else", confidence=0.85, source=FieldSource.llm)
    conflict = fuse_field(rule, llm_diff)
    assert conflict.confidence == 0.25
    assert "rule_llm_conflict" in conflict.flags


def test_fuse_prefers_present_value_when_one_side_empty():
    rule = rule_field("Only Rule")
    assert fuse_field(rule, None).value == "Only Rule"
    llm = ExtractedField(value="Only LLM", confidence=0.6, source=FieldSource.llm)
    assert fuse_field(None, llm).value == "Only LLM"


# ----------------------------------------------------------------- client replay/record

def test_replay_hit_and_missing(tmp_path):
    _write(tmp_path, "k1", {"samples": ["x"]})
    client = LLMClient(tmp_path, live=False)
    assert client.complete("prompt", key="k1").cached
    with pytest.raises(MissingFixture):
        client.complete("prompt", key="does-not-exist")


def test_live_records_then_replays(tmp_path):
    live = _FakeLiveClient(tmp_path, live=True, budget_usd=1.0)
    resp = live.complete("a prompt", key="rec1")
    assert not resp.cached and (tmp_path / "rec1.json").exists()
    replay = LLMClient(tmp_path, live=False).complete("a prompt", key="rec1")
    assert replay.cached and replay.text == resp.text


def test_budget_cap_hard_stops(tmp_path):
    broke = _FakeLiveClient(tmp_path, live=True, budget_usd=0.0)
    with pytest.raises(BudgetExceeded):
        broke.complete("x" * 4000, key="rec2")
    assert not (tmp_path / "rec2.json").exists()  # nothing spent, nothing recorded


# ----------------------------------------------------------------- field filling

def test_fill_field_self_consistency(tmp_path):
    client = LLMClient(tmp_path, live=False)
    _write(tmp_path, "d", {"samples": ["2024-09-09", "2024-09-09", "2024-09-09"]})
    f = fill_field(client, "d", parse_date)
    assert f.value == date(2024, 9, 9) and f.confidence == 0.85
    assert f.source == FieldSource.llm


def test_fill_field_partial_agreement(tmp_path):
    client = LLMClient(tmp_path, live=False)
    _write(tmp_path, "n", {"samples": ["Advik Maharaj", "Advik Maharaj", "Advik M"]})
    assert fill_field(client, "n", parse_str).confidence == 0.60


def test_malformed_reply_never_crashes(tmp_path):
    (tmp_path / "bad.json").write_text("this is not json", encoding="utf-8")
    f = fill_field(LLMClient(tmp_path, live=False), "bad", parse_str)
    assert f.value is None and f.confidence == 0.0


# ----------------------------------------------------------------- hybrid routing

def test_fallback_fills_blanks_and_skips_confident_fields(tmp_path):
    doc = ExtractedHospitalBill()
    doc.patient.name = rule_field("Confident Name")           # 0.85 -> LLM must skip it
    context = "some-document-context"
    key = _fallback_key(DocType.hospital_bill, "hospital_name", context)
    _write(tmp_path, key, {"samples": ["Acme Hospital"] * 3})

    apply_llm_fallback(doc, LLMClient(tmp_path, live=False), context)

    assert doc.hospital_name.value == "Acme Hospital"          # blank field filled by LLM
    assert doc.hospital_name.source == FieldSource.llm
    assert doc.patient.name.value == "Confident Name"          # confident rule field untouched
    assert doc.patient.name.source == FieldSource.rule
