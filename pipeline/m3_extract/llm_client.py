"""The one thin LLM client every call goes through (CLAUDE.md 'LLM usage').

Providers (`LLM_PROVIDER`):
  * `anthropic` — Claude through the official Anthropic SDK. Credentials resolve the SDK's
    usual way (`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, or an `ant auth login` profile).
  * `gemini` — Google Gemini through the official `google-genai` SDK (`GEMINI_API_KEY`).
    Its free tier is rate-limited, so live calls are paced (`LLM_MIN_INTERVAL_S`) and
    retried on 429, waiting the delay Google suggests when it sends one. Each request is
    capped at `LLM_TIMEOUT_S` and retried once on timeout. Free-tier content may be used by
    Google to improve its products — fine for the synthetic benchmark, not for real patient
    files.
Live calls log their progress (start, duration, tokens, waits) on the `mediproof.llm`
logger; `LLM_LOG_LEVEL` sets its level (default INFO).
Unset, the provider is `anthropic` when only a Claude key is configured, else `gemini` (the
provider the committed fixtures were recorded on, so a keyless clone replays them).
Keys in the repo's gitignored `.env` are loaded too.

Model race (Gemini only): when race models are configured (`LLM_RACE_MODELS`, or the
committed `race_models.json` written by `make score-models`), every structured call is sent to
all of them at once. The first reply that parses and passes the caller's `accept` check (for
the agents and chat: every quote is found in the documents) wins; slower or failing models are
ignored. If no reply passes, the first one that parsed is used, since the pipeline drops
unverifiable quotes anyway. A race reply is recorded under a model-agnostic key with a sidecar
`<key>.race.json` naming the winner and its latency, so replays show who answered. Set
`LLM_RACE=0` (the benchmark does) or pin `LLM_MODEL` for a single model.
Backup tier: `LLM_RACE_FALLBACK` models (e.g. a lighter, less congested one) join the race
when no primary has an accepted reply after `LLM_RACE_PATIENCE_S` (default 45) or when every
primary has failed, so an overloaded model never leaves a claim without an answer.
`LLM_PREFER_LIVE=1` calls the models even when a recording exists and falls back to the
recording only if the live call fails (the hosted demo uses this).

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
import logging
import os
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "llm"

log = logging.getLogger("mediproof.llm")
if not logging.getLogger().handlers and not log.handlers:
    # Nothing configured logging (uvicorn only sets up its own loggers): print to stderr
    # so live-call progress shows up in the API window.
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s [llm] %(message)s", "%H:%M:%S"))
    log.addHandler(_handler)

_MAX_RETRY_WAIT_S = 120.0

# Model race: the committed list of Gemini models that passed `make score-models`.
RACE_FILE = Path(__file__).resolve().parent / "race_models.json"
RACE_LABEL = "gemini-race"  # stands in for the model name in race fixture keys

DEFAULT_MODEL = "claude-opus-5-5"
# Gemini's default is the model that recorded tests/fixtures/llm/: fixture keys hash the model
# name, so a fresh clone must default to it or every AI feature silently replay-misses.
GEMINI_DEFAULT_MODEL = "gemini-3.5-flash-lite"
DEFAULT_MODELS = {"anthropic": DEFAULT_MODEL, "gemini": GEMINI_DEFAULT_MODEL}
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
    if os.getenv("ANTHROPIC_API_KEY") and not os.getenv("GEMINI_API_KEY"):
        return "anthropic"
    # No key or no preference: Gemini, the provider the committed fixtures were recorded on,
    # so a keyless clone replays them instead of missing every one.
    return "gemini"


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


def _retry_delay_s(details) -> float | None:
    """The wait Google suggests in a 429 body (`google.rpc.RetryInfo.retryDelay`, e.g.
    "7s" or "6.5s"), or None when the error carries no hint."""
    err = details.get("error", details) if isinstance(details, dict) else {}
    for item in (err.get("details") or []) if isinstance(err, dict) else []:
        m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)s\s*", str((item or {}).get("retryDelay", "")))
        if m:
            return float(m.group(1))
    return None


def race_models() -> list[str]:
    """Models to race: `LLM_RACE_MODELS` (comma-separated) or the committed RACE_FILE."""
    env = os.getenv("LLM_RACE_MODELS", "").strip()
    if env:
        return [m.strip() for m in env.split(",") if m.strip()]
    try:
        return list(json.loads(RACE_FILE.read_text(encoding="utf-8")).get("models", []))
    except (OSError, ValueError):
        return []


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().lower()


def quotes_found(reply, haystack: str, threshold: int = 90) -> bool:
    """True when every `quote` anywhere in `reply` appears (fuzzy, >= threshold) in
    `haystack`. The race's accept check for the agents and chat: a reply that cites text the
    documents don't contain loses to one that doesn't."""
    from rapidfuzz import fuzz

    text = _norm_text(haystack)

    def walk(node) -> bool:
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "quote" and isinstance(v, str) and v.strip():
                    if fuzz.partial_ratio(_norm_text(v), text) < threshold:
                        return False
                elif not walk(v):
                    return False
        elif isinstance(node, list):
            return all(walk(v) for v in node)
        return True

    return walk(reply)


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
        race: bool | None = None,
    ) -> None:
        _load_dotenv()
        log.setLevel(os.getenv("LLM_LOG_LEVEL", "INFO").upper())
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
        # Per-request cap on a live Gemini call; a request that never answers can't hang
        # the claim.
        self.timeout_s = float(os.getenv("LLM_TIMEOUT_S", "90"))
        self.spent_usd = 0.0
        self.calls = 0          # answered calls this run (replayed + live)
        self.live_calls = 0
        self._sdk = None
        self._last_call: dict[str, float] = {}
        self._pace_lock = threading.Lock()
        self.quota_exhausted = False
        self._exhausted: set[str] = set()   # race: models whose quota ran out this run
        # Model race (Gemini, 2+ models, no pinned model). The benchmark passes race=False so
        # its published numbers stay single-model.
        race_on = (os.getenv("LLM_RACE", "1") != "0") if race is None else race
        racers = race_models() if (race_on and self.provider == "gemini"
                                   and not model and not os.getenv("LLM_MODEL")) else []
        self.race_models = racers  # one model is fine: scoring may keep just one
        self.race_fallback = [m.strip() for m in os.getenv("LLM_RACE_FALLBACK", "").split(",")
                              if m.strip() and m.strip() not in racers] if racers else []
        self.race_patience_s = float(os.getenv("LLM_RACE_PATIENCE_S", "45"))
        self.prefer_live = os.getenv("LLM_PREFER_LIVE") == "1"
        # Who answered each structured call this run: {"model", "seconds", "replayed"}.
        self.answers: list[dict] = []
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
        t0 = self._log_start(key)
        text = self._call_provider(prompt)
        self._log_done(key, t0)
        cost = self._estimate_cost(prompt)
        return self._record(path, text, cost)

    # ------------------------------------------------------------------ structured JSON
    @property
    def racing(self) -> bool:
        return bool(self.race_models)

    def describe(self) -> str:
        """provider:model, or the race and who won it, for the dashboard."""
        if not self.racing:
            return f"{self.provider}:{self.model}"
        return f"gemini race ({', '.join(self.race_models)})"

    def json_key(self, system: str, content: list[dict] | str, schema: dict,
                 *, model: str | None = None) -> str:
        blob = json.dumps({"model": model or self.model, "system": system, "content": content,
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
        accept: Callable[[dict], bool] | None = None,
    ) -> dict:
        """Ask for a reply constrained to `schema` and return the parsed JSON object.

        `content` is the user turn: a string, or content blocks (so a shared dossier block can
        carry `cache_control` and be reused across the specialist agents' calls). `accept`
        judges a parsed reply in a model race (see the module docstring).
        Raises MissingFixture (replay miss), BudgetExceeded, LLMError or ValueError (bad JSON).
        """
        single_key = key or self.json_key(system, content, schema)
        race_key = (key or self.json_key(system, content, schema, model=RACE_LABEL)) \
            if self.racing else None
        # Replay: a race recording first, then a single-model one (the benchmark and older
        # recordings), so turning the race on never hides what is already recorded.
        hit = next((k for k in (race_key, single_key)
                    if k and self._fixture_path(k).exists()), None)
        if hit and not (self.live and self.prefer_live):
            text = self._replay(hit)
        elif not self.live:
            raise MissingFixture(f"no LLM fixture {race_key or single_key}.json and "
                                 "LLM_LIVE!=1 (run with LLM_LIVE=1 to record)")
        else:
            try:
                text = self._live_json(system, content, schema, max_tokens, accept,
                                       race_key, single_key, record=hit is None)
            except (LLMError, BudgetExceeded) as exc:
                if not hit:
                    raise
                log.warning("live call failed (%s); using the recorded reply", exc)
                text = self._replay(hit)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM fixture {hit or single_key}.json is not valid JSON") from exc

    def _replay(self, key: str) -> str:
        self.calls += 1
        meta = self._read_race_meta(key)
        self.answers.append({"model": meta.get("winner", self.model),
                             "seconds": meta.get("seconds"), "replayed": True})
        return self._fixture_path(key).read_text(encoding="utf-8")

    def _live_json(self, system, content, schema, max_tokens, accept, race_key, single_key,
                   *, record: bool) -> str:
        prompt_chars = len(system) + len(json.dumps(content, ensure_ascii=False))
        n = len(self.race_models) + len(self.race_fallback) or 1
        self._precheck(n * self._estimate_cost("x" * prompt_chars))
        if self.racing:
            text, cost, meta = self._race(system, content, schema, max_tokens, accept)
            key, model, secs = race_key, meta["winner"], meta["seconds"]
        else:
            t0 = self._log_start(single_key)
            text, cost = self._call_provider_json(system, content, schema, max_tokens)
            key, model, secs, meta = single_key, self.model, self._log_done(single_key, t0), None
        if record:
            text = self._record(self._fixture_path(key), text, cost).text
            if meta is not None:
                self._fixture_path(key).with_suffix(".race.json").write_text(
                    json.dumps(meta, indent=1), encoding="utf-8")
        else:  # prefer-live over an existing recording: keep the recording as it was
            self.spent_usd += cost
            self.calls += 1
            self.live_calls += 1
        self.answers.append({"model": model, "seconds": secs, "replayed": False})
        return text

    def last_answer(self) -> str | None:
        """'gemini-3.8-flash, 4.1s' for the most recent structured call, if any."""
        if not self.answers:
            return None
        a = self.answers[-1]
        return a["model"] + (f", {a['seconds']:.1f}s" if a.get("seconds") else "")

    def answers_summary(self, since: int = 0) -> str | None:
        """Who won the race calls since index `since`, e.g. 'won by gemini-3.8-flash x2
        (fastest 4.1s)'. None when no race answer was recorded."""
        got = self.answers[since:]
        if not self.racing or not got:
            return None
        wins: dict[str, list[float]] = {}
        for a in got:
            wins.setdefault(a["model"], []).append(a.get("seconds") or 0.0)
        parts = []
        for m, secs in sorted(wins.items(), key=lambda kv: -len(kv[1])):
            timed = [x for x in secs if x]
            parts.append(f"{m} x{len(secs)}" + (f" (fastest {min(timed):.1f}s)" if timed else ""))
        return "won by " + ", ".join(parts)

    def _read_race_meta(self, key: str) -> dict:
        try:
            return json.loads(self._fixture_path(key).with_suffix(".race.json")
                              .read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _race(self, system: str, content, schema: dict, max_tokens: int,
              accept: Callable[[dict], bool] | None) -> tuple[str, float, dict]:
        """Send one structured call to every race model at once; first accepted reply wins.
        Fallback models join after `race_patience_s` without an accepted reply, or as soon
        as every primary has failed."""
        log.info("race: %s%s", ", ".join(self.race_models),
                 f" (backup: {', '.join(self.race_fallback)})" if self.race_fallback else "")
        t0 = time.monotonic()
        pool = ThreadPoolExecutor(max_workers=len(self.race_models) + len(self.race_fallback),
                                  thread_name_prefix="llm-race")

        def launch(models: list[str]) -> dict:
            return {pool.submit(self._gemini_generate, system, content, schema, max_tokens,
                                model=m): m for m in models}

        futures = launch(self.race_models)
        pending = set(futures)
        backup_started = not self.race_fallback
        tried: dict[str, str] = {}
        fallback: tuple[str, float, str, float] | None = None
        winner: tuple[str, float, str, float] | None = None
        errors: list[Exception] = []

        def start_backup(reason: str) -> None:
            nonlocal backup_started
            backup_started = True
            log.info("race: %s; adding backup %s", reason, ", ".join(self.race_fallback))
            new = launch(self.race_fallback)
            futures.update(new)
            pending.update(new)

        try:
            while pending and winner is None:
                timeout = None if backup_started else max(
                    0.0, t0 + self.race_patience_s - time.monotonic())
                done, _ = wait(pending, timeout=timeout, return_when=FIRST_COMPLETED)
                if not done:
                    start_backup(f"no accepted reply after {self.race_patience_s:.0f}s")
                    continue
                for fut in done:
                    pending.discard(fut)
                    model, secs = futures[fut], time.monotonic() - t0
                    try:
                        text, cost = fut.result()
                        parsed = json.loads(text)
                    except Exception as exc:  # noqa: BLE001 - a racer failing just loses
                        errors.append(exc)
                        tried[model] = f"failed after {secs:.1f}s: {str(exc)[:120]}"
                        log.info("race: %s failed after %.1fs (%s)", model, secs, exc)
                        continue
                    ok = True
                    if accept is not None:
                        try:
                            ok = bool(accept(parsed))
                        except Exception:  # noqa: BLE001 - a broken check rejects
                            ok = False
                    tried[model] = f"{'accepted' if ok else 'rejected by check'} at {secs:.1f}s"
                    if ok:
                        winner = (text, cost, model, secs)
                        break
                    fallback = fallback or (text, cost, model, secs)
                if winner is None and not pending and not backup_started:
                    start_backup("no primary model gave an accepted reply")
        finally:
            pool.shutdown(wait=False, cancel_futures=True)  # losers finish in the background
        for m in self.race_models + (self.race_fallback if backup_started else []):
            tried.setdefault(m, "still running when the race was decided")
        chosen = winner or fallback
        if chosen is None:
            if errors and all(isinstance(e, QuotaExhausted) for e in errors):
                self.quota_exhausted = True
                raise QuotaExhausted("every race model is out of quota")
            raise LLMError("no race model answered: " + "; ".join(
                f"{m}: {r}" for m, r in tried.items()))
        text, cost, model, secs = chosen
        log.info("race: %s won in %.1fs%s", model, secs,
                 "" if winner else " (no reply passed the check; first valid reply used)")
        meta = {"winner": model, "seconds": round(secs, 2), "verified": winner is not None,
                "racers": tried}
        return text, cost, meta

    # ------------------------------------------------------------------ live path
    def _log_start(self, key: str) -> float:
        log.info("%s:%s call %s started (live call #%d this run)",
                 self.provider, self.model, key, self.live_calls + 1)
        return time.monotonic()

    def _log_done(self, key: str, t0: float) -> float:
        secs = time.monotonic() - t0
        log.info("call %s done in %.1fs", key, secs)
        return round(secs, 2)

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

    def _pace(self, model: str | None = None) -> None:
        # Free-tier limits are per model, so each model is paced on its own clock. The slot
        # is reserved under the lock so racing threads never double-book a model.
        model = model or self.model
        with self._pace_lock:
            now = time.monotonic()
            slot = max(now, self._last_call.get(model, 0.0) + self.min_interval_s)
            self._last_call[model] = slot
        wait = slot - now
        if wait > 0:
            log.debug("pacing %s: waiting %.1fs before the next call", model, wait)
            time.sleep(wait)

    # ------------------------------------------------------------------ Gemini
    def _gemini(self):  # pragma: no cover - needs a live key
        if self._sdk is None:
            from google import genai
            from google.genai import types

            key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            if not key:
                raise LLMError("LLM_PROVIDER=gemini but GEMINI_API_KEY is unset")
            self._sdk = genai.Client(
                api_key=key, http_options=types.HttpOptions(timeout=int(self.timeout_s * 1000)))
        return self._sdk

    def _gemini_generate(self, system: str | None, content, schema: dict | None,
                         max_tokens: int, *, model: str | None = None) -> tuple[str, float]:
        """One Gemini call (paced, retried on rate limits and once on timeout). Content
        blocks become parts; Anthropic-only keys such as cache_control are dropped."""
        import httpx
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
        model = model or self.model
        if model in self._exhausted or (self.quota_exhausted and not self.racing):
            raise QuotaExhausted(f"{model} quota already exhausted this run; not calling again")
        client = self._gemini()
        timed_out = False
        for attempt in range(3):
            self._pace(model)
            try:
                resp = client.models.generate_content(model=model, contents=parts,
                                                      config=config)
                break
            except httpx.TimeoutException as exc:
                if timed_out:
                    log.warning("no answer within %.0fs again; giving up", self.timeout_s)
                    raise LLMError(
                        f"Gemini did not answer within {self.timeout_s:.0f}s") from exc
                timed_out = True
                log.warning("no answer within %.0fs; retrying once", self.timeout_s)
            except httpx.TransportError as exc:
                raise LLMError(f"could not reach the Gemini API: {exc}") from exc
            except errors.APIError as exc:
                msg = str(exc.message or exc)
                if exc.code == 429 and ("per day" in msg.lower() or "perday" in msg.lower()
                                        or attempt == 2):
                    # A daily quota won't recover by waiting: stop, don't keep hammering.
                    self._exhausted.add(model)
                    if not self.racing:
                        self.quota_exhausted = True
                    log.warning("%s quota exhausted (429); no more calls to it this run", model)
                    raise QuotaExhausted(f"Gemini quota exhausted (429): {msg[:200]}") from exc
                # 429 per-minute quota or 500/503 overload: back off, at most 3 tries. Wait
                # what Google suggests when it says; otherwise 30s, then 60s.
                if exc.code in (429, 500, 503) and attempt < 2:
                    hint = _retry_delay_s(exc.details) if exc.code == 429 else None
                    wait = min(hint + 1, _MAX_RETRY_WAIT_S) if hint is not None \
                        else 30.0 * (attempt + 1)
                    log.warning("Gemini %s (%s); waiting %.0fs, retry %d/2", exc.code,
                                "rate-limited" if exc.code == 429 else "overloaded",
                                wait, attempt + 1)
                    time.sleep(wait)
                    continue
                raise LLMError(f"Gemini API error {exc.code}: {msg[:200]}") from exc
        else:
            raise LLMError("Gemini gave no answer after 3 attempts")
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
        if u:
            log.info("%s reply: %d tokens in / %d out (incl. %d thinking)", model,
                     u.prompt_token_count or 0, tokens_out, u.thoughts_token_count or 0)
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
