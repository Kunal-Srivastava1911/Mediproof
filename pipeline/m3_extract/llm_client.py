"""The one thin LLM client every call goes through (CLAUDE.md 'LLM usage').

Providers (`LLM_PROVIDER`):
  * `anthropic` — Claude through the official Anthropic SDK. Credentials resolve the SDK's
    usual way (`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, or an `ant auth login` profile).
  * `gemini` — Google Gemini through the official `google-genai` SDK (`GEMINI_API_KEY`).
    Its free tier is rate-limited, so live calls are paced (`LLM_MIN_INTERVAL_S`) and
    retried on 429. Free-tier content may be used by Google to improve its products — fine
    for the synthetic benchmark, not for real patient files.
Unset, the provider is `gemini` when only a Gemini key is configured, else `anthropic`.
Keys in the repo's gitignored `.env` are loaded too.

Record/replay: responses are keyed and cached under `tests/fixtures/llm/`. Tests and CI
replay from fixtures — deterministic, free, fast. A live provider call happens **only** when
`LLM_LIVE=1`; it records its reply so the next run replays it. A fixture key hashes the
model, system prompt, content and output schema, so changing any of them re-records.

Budget cap: cumulative live spend is checked against `LLM_BUDGET_USD` and hard-stops with a
`BudgetExceeded` before any call that would breach it; actual spend is then booked from the
response's token usage.

Output contract: `complete_json` constrains the reply to a JSON schema (structured outputs)
and returns the parsed object. Callers treat any failure as "no answer" — the pipeline never
crashes on a malformed reply.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "llm"

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_MODELS = {"anthropic": DEFAULT_MODEL, "gemini": "gemini-3.8-flash"}
# USD per million (input, output) tokens. Cache writes bill at 1.25x input, reads at 0.1x.
# Gemini is booked at $0: the free tier is the intended use (set LLM_PRICE_IN/OUT for paid).
_PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}


def _provider() -> str:
    explicit = os.getenv("LLM_PROVIDER", "").strip().lower()
    if explicit in DEFAULT_MODELS:
        return explicit
    if os.getenv("GEMINI_API_KEY") and not os.getenv("ANTHROPIC_API_KEY"):
        return "gemini"
    return "anthropic"


class BudgetExceeded(RuntimeError):
    """Raised when a live call would exceed LLM_BUDGET_USD."""


class MissingFixture(LookupError):
    """No recorded fixture for this key and live calls are disabled."""


class LLMError(RuntimeError):
    """The provider returned no usable answer (refusal, truncation, API error)."""


class QuotaExhausted(LLMError):
    """The provider's quota is used up (e.g. a free tier's daily limit): stop calling it."""


@dataclass
class LLMResponse:
    text: str
    cost_usd: float
    cached: bool


def _key_for(model: str, prompt: str) -> str:
    return hashlib.sha1(f"{model}\n{prompt}".encode()).hexdigest()[:16]


def _load_dotenv(path: Path = _REPO_ROOT / ".env") -> None:
    """Load KEY=VALUE lines from the repo's .env without overriding the real environment.
    Skipped when MEDIPROOF_NO_DOTENV=1 (the test suite sets it, so a developer's keys and
    LLM settings never leak into tests)."""
    if os.getenv("MEDIPROOF_NO_DOTENV") == "1" or not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if "=" in line:
            k, v = line.split("=", 1)
            if k.strip() and v.strip():
                os.environ.setdefault(k.strip(), v.strip())


class LLMClient:
    """Deterministic-by-default gateway to Claude for extraction fallback and the agents."""

    def __init__(
        self,
        fixtures_dir: str | Path | None = None,
        *,
        live: bool | None = None,
        budget_usd: float | None = None,
        model: str | None = None,
        effort: str | None = None,
    ) -> None:
        _load_dotenv()
        self.fixtures_dir = Path(fixtures_dir or os.getenv("LLM_FIXTURES", _DEFAULT_FIXTURES))
        self.live = (os.getenv("LLM_LIVE") == "1") if live is None else live
        self.budget_usd = float(os.getenv("LLM_BUDGET_USD", "1.00")) if budget_usd is None \
            else budget_usd
        self.provider = _provider()
        self.model = model or os.getenv("LLM_MODEL") or DEFAULT_MODELS[self.provider]
        self.effort = effort or os.getenv("LLM_EFFORT", "medium")
        # Server-side refusal fallback (Claude API only). Set LLM_FALLBACKS=0 on platforms
        # that reject it.
        self.fallbacks = os.getenv("LLM_FALLBACKS", "1") != "0"
        # Minimum seconds between live calls (free tiers are rate-limited per minute).
        default_gap = "6" if self.provider == "gemini" else "0"
        self.min_interval_s = float(os.getenv("LLM_MIN_INTERVAL_S", default_gap))
        self.spent_usd = 0.0
        self.calls = 0          # answered calls this run (replayed + live)
        self.live_calls = 0
        self._sdk = None
        self._last_call = 0.0
        self.quota_exhausted = False
        # "combined": one call covers all five specialist areas (2 calls/claim incl. the
        # skeptic) — the default on Gemini's free tier; "separate": one call per agent.
        self.agent_mode = os.getenv(
            "LLM_AGENT_MODE", "combined" if self.provider == "gemini" else "separate")

    def _fixture_path(self, key: str) -> Path:
        return self.fixtures_dir / f"{key}.json"

    # ------------------------------------------------------------------ text (M3 fallback)
    def complete(self, prompt: str, *, key: str | None = None) -> LLMResponse:
        """Return the model's reply text for `prompt`, from fixture if recorded."""
        key = key or _key_for(self.model, prompt)
        path = self._fixture_path(key)
        if path.exists():
            self.calls += 1
            return LLMResponse(text=path.read_text(encoding="utf-8"), cost_usd=0.0, cached=True)
        if not self.live:
            raise MissingFixture(
                f"no LLM fixture {key}.json and LLM_LIVE!=1 (run with LLM_LIVE=1 to record)"
            )
        self._precheck(self._estimate_cost(prompt))
        text = self._call_provider(prompt)
        cost = self._estimate_cost(prompt)
        return self._record(path, text, cost)

    # ------------------------------------------------------------------ structured JSON
    def json_key(self, system: str, content: list[dict] | str, schema: dict) -> str:
        blob = json.dumps({"model": self.model, "system": system, "content": content,
                           "schema": schema}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha1(blob.encode()).hexdigest()[:16]

    def complete_json(
        self,
        system: str,
        content: list[dict] | str,
        schema: dict,
        *,
        key: str | None = None,
        max_tokens: int = 16000,
    ) -> dict:
        """Ask for a reply constrained to `schema` and return the parsed JSON object.

        `content` is the user turn: a string, or content blocks (so a shared dossier block can
        carry `cache_control` and be reused across the specialist agents' calls).
        Raises MissingFixture (replay miss), BudgetExceeded, LLMError or ValueError (bad JSON).
        """
        key = key or self.json_key(system, content, schema)
        path = self._fixture_path(key)
        if path.exists():
            self.calls += 1
            text = path.read_text(encoding="utf-8")
        elif not self.live:
            raise MissingFixture(
                f"no LLM fixture {key}.json and LLM_LIVE!=1 (run with LLM_LIVE=1 to record)")
        else:
            prompt_chars = len(system) + len(json.dumps(content, ensure_ascii=False))
            self._precheck(self._estimate_cost("x" * prompt_chars))
            text, cost = self._call_provider_json(system, content, schema, max_tokens)
            text = self._record(path, text, cost).text
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM fixture {key}.json is not valid JSON") from exc

    # ------------------------------------------------------------------ live path
    def _precheck(self, est: float) -> None:
        # Estimate before spending so the budget cap is a hard pre-check (plan §8).
        if self.spent_usd + est > self.budget_usd:
            raise BudgetExceeded(
                f"live call would spend ~${est:.4f}; ${self.spent_usd:.4f} of "
                f"LLM_BUDGET_USD=${self.budget_usd:.2f} already used"
            )

    def _record(self, path: Path, text: str, cost: float) -> LLMResponse:
        self.spent_usd += cost
        self.calls += 1
        self.live_calls += 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return LLMResponse(text=text, cost_usd=cost, cached=False)

    def _prices(self) -> tuple[float, float]:
        if os.getenv("LLM_PRICE_IN") or os.getenv("LLM_PRICE_OUT"):
            return float(os.getenv("LLM_PRICE_IN", "0")), float(os.getenv("LLM_PRICE_OUT", "0"))
        if self.provider == "gemini":
            return 0.0, 0.0
        return _PRICES.get(self.model, _PRICES[DEFAULT_MODEL])

    def _estimate_cost(self, prompt: str) -> float:
        # ~4 chars/token on the input side; the output side is booked from real usage.
        in_price, _ = self._prices()
        return round((len(prompt) / 4) / 1_000_000 * in_price, 6)

    def _cost_from_usage(self, usage) -> float:
        in_price, out_price = self._prices()
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        tokens_in = usage.input_tokens + 1.25 * cache_write + 0.1 * cache_read
        return round((tokens_in * in_price + usage.output_tokens * out_price) / 1_000_000, 6)

    def _pace(self) -> None:
        wait = self._last_call + self.min_interval_s - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    # ------------------------------------------------------------------ Gemini
    def _gemini(self):  # pragma: no cover - needs a live key
        if self._sdk is None:
            from google import genai

            key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            if not key:
                raise LLMError("LLM_PROVIDER=gemini but GEMINI_API_KEY is unset")
            self._sdk = genai.Client(api_key=key)
        return self._sdk

    def _gemini_generate(self, system: str | None, content, schema: dict | None,
                         max_tokens: int) -> tuple[str, float]:
        """One Gemini call (paced, retried on rate limits). Content blocks become parts;
        Anthropic-only keys such as cache_control are dropped."""
        from google.genai import errors, types

        if isinstance(content, str):
            parts = [content]
        else:
            parts = [b["text"] for b in content if b.get("type") == "text"]
        config = types.GenerateContentConfig(
            system_instruction=system or None,
            max_output_tokens=max_tokens,
            response_mime_type="application/json" if schema else None,
            response_json_schema=schema,
        )
        if self.quota_exhausted:
            raise QuotaExhausted("Gemini quota already exhausted this run; not calling again")
        client = self._gemini()
        for attempt in range(3):
            self._pace()
            try:
                resp = client.models.generate_content(model=self.model, contents=parts,
                                                      config=config)
                break
            except errors.APIError as exc:
                msg = str(exc.message or exc)
                if exc.code == 429 and ("per day" in msg.lower() or "perday" in msg.lower()
                                        or attempt == 2):
                    # A daily quota won't recover by waiting: stop, don't keep hammering.
                    self.quota_exhausted = True
                    raise QuotaExhausted(f"Gemini quota exhausted (429): {msg[:200]}") from exc
                # 429 per-minute quota or 500/503 overload: back off, at most 3 tries.
                if exc.code in (429, 500, 503) and attempt < 2:
                    time.sleep(30 * (attempt + 1))
                    continue
                raise LLMError(f"Gemini API error {exc.code}: {msg[:200]}") from exc
        if not resp.candidates:
            raise LLMError("Gemini returned no answer (prompt blocked)")
        reason = str(resp.candidates[0].finish_reason or "")
        if "MAX_TOKENS" in reason:
            raise LLMError("reply truncated at max_output_tokens")
        text = resp.text
        if not text:
            raise LLMError(f"Gemini returned no text (finish reason {reason or 'unknown'})")
        u = resp.usage_metadata
        in_price, out_price = self._prices()
        tokens_out = (u.candidates_token_count or 0) + (u.thoughts_token_count or 0) if u else 0
        cost = ((u.prompt_token_count or 0) * in_price + tokens_out * out_price) / 1e6 \
            if u else 0.0
        return text, round(cost, 6)

    def _client(self):  # pragma: no cover - needs a live key
        if self._sdk is None:
            import anthropic

            self._sdk = anthropic.Anthropic()
        return self._sdk

    def _create(self, **kwargs):  # pragma: no cover - needs a live key
        import anthropic

        client = self._client()
        try:
            if self.fallbacks:
                resp = client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
            else:
                resp = client.messages.create(**kwargs)
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Claude API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("could not reach the Claude API") from exc
        if resp.stop_reason == "refusal":
            raise LLMError("Claude declined this request")
        if resp.stop_reason == "max_tokens":
            raise LLMError("reply truncated at max_tokens")
        text = "".join(b.text for b in resp.content if b.type == "text")
        return text, self._cost_from_usage(resp.usage)

    def _call_provider(self, prompt: str) -> str:  # pragma: no cover - needs a live key
        """Plain-text completion. Only reached under LLM_LIVE=1."""
        if self.provider == "gemini":
            return self._gemini_generate(None, prompt, None, 16000)[0]
        self._pace()
        text, _ = self._create(
            model=self.model, max_tokens=16000,
            output_config={"effort": self.effort},
            messages=[{"role": "user", "content": prompt}],
        )
        return text

    def _call_provider_json(
        self, system: str, content: list[dict] | str, schema: dict, max_tokens: int
    ) -> tuple[str, float]:  # pragma: no cover - needs a live key
        """Structured-output completion. Only reached under LLM_LIVE=1."""
        if self.provider == "gemini":
            return self._gemini_generate(system, content, schema, max_tokens)
        self._pace()
        return self._create(
            model=self.model, max_tokens=max_tokens, system=system,
            output_config={"effort": self.effort,
                           "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": content}],
        )
