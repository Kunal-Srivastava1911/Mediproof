"""Gemini model race: first reply that passes the caller's check wins; replays are stable."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from pipeline.m3_extract.llm_client import LLMClient, LLMError, MissingFixture, quotes_found

SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}}
DOC = "Discharge summary: patient spent 1 day in the ICU. Bill: ICU charges x 3 days."


def _reply(text: str):
    return SimpleNamespace(
        candidates=[SimpleNamespace(finish_reason="STOP")], text=text,
        usage_metadata=SimpleNamespace(prompt_token_count=10, candidates_token_count=5,
                                       thoughts_token_count=0))


def _client(tmp_path, monkeypatch, behaviour: dict, *, live=True) -> LLMClient:
    """behaviour: model -> (delay_s, reply_text or Exception)."""
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_MIN_INTERVAL_S", "0")
    monkeypatch.setenv("LLM_RACE_MODELS", ",".join(behaviour))
    client = LLMClient(tmp_path, live=live, race=True)

    def generate_content(model, contents, config):
        delay, out = behaviour[model]
        time.sleep(delay)
        if isinstance(out, Exception):
            raise out
        return _reply(out)

    client._sdk = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    return client


def _good(quote="spent 1 day in the ICU"):
    return json.dumps({"answer": "1 day", "sources": [{"document_id": "DS", "quote": quote}]})


def test_fastest_verified_reply_wins_over_a_faster_unverified_one(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, {
        "fast-but-wrong": (0.0, _good(quote="patient spent 9 days in the ward")),
        "steady": (0.2, _good()),
        "slow": (1.5, _good()),
    })
    t0 = time.monotonic()
    out = client.complete_json("sys", "q", SCHEMA, accept=lambda r: quotes_found(r, DOC))
    assert out["answer"] == "1 day"
    assert client.answers[-1]["model"] == "steady"
    assert time.monotonic() - t0 < 1.0  # did not wait for the slow model
    meta = json.loads(next(tmp_path.glob("*.race.json")).read_text())
    assert meta["winner"] == "steady" and meta["verified"] is True
    assert meta["racers"]["fast-but-wrong"].startswith("rejected by check")


def test_failed_racer_loses_and_unverified_fallback_is_used(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, {
        "broken": (0.0, RuntimeError("503 overloaded")),
        "unverified": (0.1, _good(quote="not in the file at all")),
    })
    client.complete_json("sys", "q", SCHEMA, accept=lambda r: quotes_found(r, DOC))
    meta = json.loads(next(tmp_path.glob("*.race.json")).read_text())
    assert meta["winner"] == "unverified" and meta["verified"] is False
    assert meta["racers"]["broken"].startswith("failed")


def test_all_racers_failing_raises(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, {
        "a": (0.0, RuntimeError("boom")), "b": (0.0, ValueError("bad")),
    })
    with pytest.raises(LLMError):
        client.complete_json("sys", "q", SCHEMA)


def test_race_recording_replays_offline_with_the_winner(tmp_path, monkeypatch):
    live = _client(tmp_path, monkeypatch, {"a": (0.0, _good()), "b": (0.3, _good())})
    live.complete_json("sys", "q", SCHEMA)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    replay = LLMClient(tmp_path, live=False, race=True)
    assert replay.complete_json("sys", "q", SCHEMA)["answer"] == "1 day"
    assert replay.answers[-1] == {"model": "a", "seconds": pytest.approx(0, abs=0.3),
                                  "replayed": True}
    with pytest.raises(MissingFixture):
        replay.complete_json("sys", "another question", SCHEMA)


def test_race_falls_back_to_single_model_recordings(tmp_path, monkeypatch):
    """Turning the race on must not hide what the benchmark already recorded."""
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    single = LLMClient(tmp_path, live=False, race=False)
    (tmp_path / f"{single.json_key('sys', 'q', SCHEMA)}.json").write_text('{"answer": "old"}')
    monkeypatch.setenv("LLM_RACE_MODELS", "a,b")
    racing = LLMClient(tmp_path, live=False, race=True)
    assert racing.racing and racing.complete_json("sys", "q", SCHEMA)["answer"] == "old"


def test_race_is_off_without_models_or_when_a_model_is_pinned(tmp_path, monkeypatch):
    from pipeline.m3_extract import llm_client

    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_RACE_MODELS", "")
    monkeypatch.setattr(llm_client, "RACE_FILE", tmp_path / "none.json")
    assert not LLMClient(tmp_path, race=True).racing
    monkeypatch.setenv("LLM_RACE_MODELS", "a,b")
    assert LLMClient(tmp_path, race=True).racing
    assert not LLMClient(tmp_path, race=False).racing
    monkeypatch.setenv("LLM_MODEL", "a")
    assert not LLMClient(tmp_path, race=True).racing


def test_quotes_found_checks_every_quote():
    assert quotes_found({"x": [{"quote": "1 day in the ICU"}]}, DOC)
    assert not quotes_found({"x": [{"quote": "1 day in the ICU"}, {"quote": "MRI brain"}]}, DOC)
    assert quotes_found({"answer": "no quotes at all"}, DOC)
