"""Recording the test pack with a (fake) Gemini race, then replaying it with no key, leaves
no AI feature missing. Guards the whole chain: file-hash claim ids, race keys + sidecars,
and the API's agent / Hindi / chat paths."""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest

from pipeline.m3_extract.llm_client import LLMClient


def _fake_for(schema: dict | None, contents) -> str:
    props = (schema or {}).get("properties", {})
    if "translations" in props:  # one translation per numbered detail line, numbers kept
        lines = [re.sub(r"^\d+\.\s*", "", ln) for ln in contents[0].splitlines() if ln.strip()]
        return json.dumps({"translations": [f"[hi] {ln}" for ln in lines]})
    if "answer" in props:
        return json.dumps({"answer": "From your documents.", "sources": []})

    def fill(s):
        t = s.get("type")
        if t == "object":
            return {k: fill(v) for k, v in s.get("properties", {}).items()
                    if k in s.get("required", [])}
        return {"array": [], "string": "", "number": 0, "integer": 0,
                "boolean": False}.get(t, None)
    return json.dumps(fill(schema or {"type": "object"}))


@pytest.mark.slow
def test_record_then_keyless_replay(tmp_path, monkeypatch):
    from scripts import testpack

    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_RACE", "1")
    monkeypatch.setenv("LLM_RACE_MODELS", "fake-a,fake-b")
    monkeypatch.setenv("LLM_MIN_INTERVAL_S", "0")
    monkeypatch.setenv("LLM_FIXTURES", str(tmp_path))
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-for-test")

    def generate_content(model, contents, config):
        text = _fake_for(config.response_json_schema, contents)
        return SimpleNamespace(candidates=[SimpleNamespace(finish_reason="STOP")], text=text,
                               usage_metadata=None)

    fake = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    monkeypatch.setattr(LLMClient, "_gemini", lambda self: fake)

    assert testpack.cmd_record_or_check(live=True) == 0
    assert list(tmp_path.glob("*.race.json")), "race recordings carry a winner sidecar"

    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.setattr(LLMClient, "_gemini", lambda self: pytest.fail("went live offline"))
    assert testpack.cmd_record_or_check(live=False) == 0
