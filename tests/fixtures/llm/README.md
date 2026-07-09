# tests/fixtures/llm — recorded LLM replies

Every LLM call in MediProof goes through `pipeline/m3_extract/llm_client.py`. Replies are
**recorded here and replayed** so tests and CI are deterministic, free, and offline
(CLAUDE.md 'LLM usage').

- **Replay (default).** A fixture is looked up by key: `<key>.json`, where the key is a hash
  of `model + prompt` (or an explicit key the caller passes). Its contents are the raw model
  reply text — for field extraction, `{"samples": ["v1", "v2", "v3"]}` (the k=3 self-
  consistency samples the fusion layer scores).
- **Record.** Run with `LLM_LIVE=1` and `GEMINI_API_KEY` set: the client calls the provider,
  writes the reply here, and every later run replays it. Live spend is capped by
  `LLM_BUDGET_USD`.

A missing fixture (offline, no `LLM_LIVE`) or a malformed reply degrades to
`value=None, confidence=0` — the pipeline never crashes on the LLM.
