"""The one thin LLM client every call goes through (CLAUDE.md 'LLM usage').

Record/replay: responses are keyed and cached under `tests/fixtures/llm/`. Tests and CI
replay from fixtures — deterministic, free, fast. A live provider call happens **only** when
`LLM_LIVE=1` (and a key is set); it records its reply so the next run replays it.

Budget cap: cumulative live spend is checked against `LLM_BUDGET_USD` and hard-stops with a
`BudgetExceeded` before any call that would breach it.

Output contract (enforced by callers, see `fuse.py`): a reply must parse into the target
field's schema; on failure the caller falls back to `value=None, confidence=0` — the pipeline
never crashes on a malformed reply.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "llm"


class BudgetExceeded(RuntimeError):
    """Raised when a live call would exceed LLM_BUDGET_USD."""


class MissingFixture(LookupError):
    """No recorded fixture for this key and live calls are disabled."""


@dataclass
class LLMResponse:
    text: str
    cost_usd: float
    cached: bool


def _key_for(model: str, prompt: str) -> str:
    return hashlib.sha1(f"{model}\n{prompt}".encode()).hexdigest()[:16]


class LLMClient:
    """Deterministic-by-default gateway to the (V)LM used for M3's fallback layer."""

    def __init__(
        self,
        fixtures_dir: str | Path | None = None,
        *,
        live: bool | None = None,
        budget_usd: float | None = None,
        model: str | None = None,
    ) -> None:
        self.fixtures_dir = Path(fixtures_dir or os.getenv("LLM_FIXTURES", _DEFAULT_FIXTURES))
        self.live = (os.getenv("LLM_LIVE") == "1") if live is None else live
        self.budget_usd = float(os.getenv("LLM_BUDGET_USD", "1.00")) if budget_usd is None \
            else budget_usd
        self.model = model or os.getenv("LLM_MODEL", "gemini-1.5-flash")
        self.spent_usd = 0.0

    def _fixture_path(self, key: str) -> Path:
        return self.fixtures_dir / f"{key}.json"

    def complete(self, prompt: str, *, key: str | None = None) -> LLMResponse:
        """Return the model's reply text for `prompt`, from fixture if recorded."""
        key = key or _key_for(self.model, prompt)
        path = self._fixture_path(key)
        if path.exists():
            return LLMResponse(text=path.read_text(encoding="utf-8"), cost_usd=0.0, cached=True)
        if not self.live:
            raise MissingFixture(
                f"no LLM fixture {key}.json and LLM_LIVE!=1 (run with LLM_LIVE=1 to record)"
            )
        return self._call_live_and_record(prompt, key, path)

    # ------------------------------------------------------------------ live path
    def _call_live_and_record(self, prompt: str, key: str, path: Path) -> LLMResponse:
        # Estimate cost before spending so the budget cap is a hard pre-check (plan §8).
        est = self._estimate_cost(prompt)
        if self.spent_usd + est > self.budget_usd:
            raise BudgetExceeded(
                f"live call would spend ${est:.4f}, over LLM_BUDGET_USD=${self.budget_usd:.2f}"
            )
        text = self._call_provider(prompt)  # provider-specific; not exercised in tests
        self.spent_usd += est
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return LLMResponse(text=text, cost_usd=est, cached=False)

    def _estimate_cost(self, prompt: str) -> float:
        # Rough Flash-tier estimate: ~$0.075 / 1M input tokens, ~4 chars/token.
        return round((len(prompt) / 4) / 1_000_000 * 0.075, 6)

    def _call_provider(self, prompt: str) -> str:  # pragma: no cover - needs a live key
        """Call Gemini's generateContent REST endpoint. Only reached under LLM_LIVE=1."""
        import urllib.request

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("LLM_LIVE=1 but GEMINI_API_KEY is unset")
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{self.model}:generateContent?key={api_key}")
        body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return data["candidates"][0]["content"]["parts"][0]["text"]
