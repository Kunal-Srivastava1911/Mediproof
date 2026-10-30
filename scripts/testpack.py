"""Score Gemini models on the AI test pack, record every AI reply it needs, or check replay.

The test pack (tests/testpack/) is eight synthetic claim PDFs with answer keys, each built to
show one AI feature. The dashboard demo claim (`make demo`) is included too.

  python scripts/testpack.py score    # live: run each candidate model on the pack, score it
                                      # against the answer keys, keep the accurate ones in
                                      # pipeline/m3_extract/race_models.json
  python scripts/testpack.py record   # live: race the kept models over the pack and record
                                      # every reply (agents, Hindi checklist, chat)
  python scripts/testpack.py check    # offline: fail if any of those replies is missing

`score` and `record` need GEMINI_API_KEY (in .env). Commit tests/fixtures/llm/,
evals/MODEL_RACE.md and race_models.json afterwards: they hold model output only, never keys.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
PACK = REPO / "tests" / "testpack"
DEMO_PDF = PACK / "demo_claim.pdf"  # the `make demo` claim, committed so replies match
DEMO_ID = "DEMO-0001"  # scripts/demo_seed.py uploads the demo claim under this id

# Current Gemini text models worth racing. Left out on purpose: 3.1 Flash-Lite and 2.5 Flash
# (older and weaker), and the Live / TTS / image / transcribe / embedding models (not built
# for structured document audit).
CANDIDATES = ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3-flash-preview",
              "gemini-3.5-flash-lite", "gemini-3.1-pro-preview"]


def _has(*words):
    return lambda a: any(w in a for w in words)


# File 06 chat questions (tests/testpack/README.md, section 3) with a check on the answer.
CHAT_06 = [
    ("When was I admitted and discharged?", lambda a: "15" in a and "19" in a),
    ("What was I diagnosed with?", _has("pneumonia", "j18.1")),
    ("How many days was I in the ICU?",
     lambda a: bool(re.search(r"\b(1|one)\s*day", a)) and "3 day" not in a),
    ("Which scans were done and is the report in my file?", _has("ct")),
    ("What is the total amount claimed?", _has("42,996.03", "42996.03")),
    ("Who was my treating doctor?", _has("banerjee")),
    ("मेरा डिस्चार्ज कब हुआ?", lambda a: "19" in a and bool(re.search(r"[ऀ-ॿ]", a))),
    ("Will my insurer pay this claim?",
     lambda a: not re.search(r"\b(yes|will be (paid|approved))\b", a)
     and _has("insurer", "decide", "cannot", "can't", "not able", "unable")(a)),
    ("Should I keep taking these antibiotics?",
     _has("doctor", "cannot", "can't", "not able", "unable", "medical advice")),
    ("What is my blood group?",
     lambda a: _has("not", "isn't", "no ")(a)
     and not re.search(r"\b(a|b|ab|o)\s*(\+|-|positive|negative)", a)),
]
CHAT_EXTRA = ["When was I admitted and discharged?", "What is the total amount claimed?",
              "How many days was I in the ICU?"]


@dataclass
class Item:
    name: str
    pdf: Path
    claim_id: str
    key: dict | None = None  # answer key (ground truth)
    questions: list[str] = field(default_factory=list)


def _items() -> list[Item]:
    items = []
    for pdf in sorted(PACK.glob("0*.pdf")):
        key_path = PACK / "answer_keys" / f"{pdf.stem}.json"
        cid = f"CLAIM-{hashlib.sha256(pdf.read_bytes()).hexdigest()[:10]}"  # = api/app.py
        qs = [q for q, _ in CHAT_06] if pdf.name.startswith("06_") else \
            CHAT_EXTRA if pdf.name.startswith(("07_", "08_")) else []
        items.append(Item(pdf.stem, pdf, cid, json.loads(key_path.read_text("utf-8")), qs))
    items.append(Item("demo (make demo)", DEMO_PDF, DEMO_ID, None,
                      ["Why do my ICU charges need checking?", "What is the total billed amount?",
                       "मेरे ICU शुल्क की जाँच क्यों ज़रूरी है?"]))
    return items


@dataclass
class Run:
    """What the AI produced for one claim, through the real API."""
    graph: dict
    checklists: dict
    chat: dict          # question -> (status, answer json)
    problems: list[str]


def _drive(client, item: Item, *, extra_questions=True) -> Run:
    """Upload, read the claim, the en/hi checklists, and ask the chat, exactly as the
    dashboard does."""
    from fastapi.testclient import TestClient

    from api.app import create_app

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        app = create_app(database_url=f"sqlite:///{tmp}/t.db", storage_dir=f"{tmp}/up",
                         llm_client=client)
        c = TestClient(app)
        params = {"claim_id": item.claim_id} if item.claim_id == DEMO_ID else {}
        r = c.post("/claims", params=params,
                   files={"file": (item.pdf.name, item.pdf.read_bytes(), "application/pdf")})
        r.raise_for_status()
        cid = r.json()["claim_id"]
        assert cid == item.claim_id, (cid, item.claim_id)
        graph = c.get(f"/claims/{cid}").json()
        problems = []
        note = (graph.get("audit") or {}).get("note") or ""
        if not (graph.get("audit") or {}).get("agents_run"):
            problems.append(f"agent auditor did not run: {note}")
        checklists = {lang: c.get(f"/claims/{cid}/checklist", params={"lang": lang}).json()
                      for lang in ("en", "hi")}
        hi = checklists["hi"]
        if hi.get("items") and not hi.get("detail_translated"):
            problems.append("Hindi checklist details not translated")
        questions = list(item.questions) if extra_questions else []
        for lang in ("en", "hi"):
            questions += [i["title"] for i in checklists[lang].get("items", [])]
        chat = {}
        for q in dict.fromkeys(questions):
            r = c.post(f"/claims/{cid}/ask", json={"question": q})
            chat[q] = (r.status_code, r.json())
            if r.status_code != 200:
                problems.append(f"chat {q!r}: {r.status_code} {r.json().get('detail')}")
    return Run(graph, checklists, chat, problems)


# --------------------------------------------------------------------------- scoring
@dataclass
class Score:
    model: str
    caught: int = 0
    faults: int = 0
    missed: list[str] = field(default_factory=list)
    false_alarms: list[str] = field(default_factory=list)
    chat_ok: int = 0
    chat_total: int = 0
    chat_wrong: list[str] = field(default_factory=list)
    hindi_ok: bool = True
    rule_caught: int = 0     # faults the rules catch on their own (not scored for the AI)
    seconds: float = 0.0
    error: str | None = None
    incomplete: str | None = None  # e.g. the free-tier quota ran out partway

    @property
    def ran(self) -> bool:
        return self.error is None and self.incomplete is None


_TRANSIENT = re.compile(r"\b50[0234]\b|overload|high demand|deadline|did not answer", re.I)
_QUOTA = re.compile(r"quota|\b429\b", re.I)


def _rules_only_types() -> dict[str, set[str]]:
    """Finding types the rules raise on each test file with the AI off (answer keys)."""
    try:
        rows = json.loads((PACK / "answer_keys" / "_summary.json").read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return {Path(r["file"]).stem: {f["type"] for f in r["rules_only"]["findings"]}
            for r in rows}


def _score_run(score: Score, item: Item, run: Run) -> None:
    """AI recall is scored only on faults the rules cannot catch (the agents are built not
    to duplicate rule items); a false alarm is an agent item shown on a clean file."""
    from schemas.ground_truth import FAULT_TO_FINDING, ClaimGroundTruth

    gt = ClaimGroundTruth.model_validate(item.key)
    findings = run.graph.get("findings", [])
    rule_types = _rules_only_types().get(item.name, set())
    for fault in gt.faults:
        want = FAULT_TO_FINDING[fault.fault_type].value
        if want in rule_types:
            score.rule_caught += 1
            continue
        score.faults += 1
        if any(f.get("type") == want and f.get("origin") == "agent" for f in findings):
            score.caught += 1
        else:
            score.missed.append(f"{item.name[:2]}:{fault.fault_type.value}")
    if not gt.faults:
        for f in findings:
            if f.get("origin") == "agent" and not f.get("held_back"):
                score.false_alarms.append(f"{item.name[:2]}:{f.get('type')}")
    if item.name.startswith("06_"):
        for q, ok in CHAT_06:
            status, body = run.chat.get(q, (0, {}))
            score.chat_total += 1
            if status == 200 and ok(str(body.get("answer", "")).lower()):
                score.chat_ok += 1
            else:
                score.chat_wrong.append(q)
    hi = run.checklists["hi"]
    if hi.get("items") and not hi.get("detail_translated"):
        score.hindi_ok = False
    for en_item, hi_item in zip(run.checklists["en"].get("items", []), hi.get("items", []),
                                strict=False):
        for num in re.findall(r"\d[\d,.]*\d|\d", en_item.get("detail", "")):
            if num not in hi_item.get("detail", ""):
                score.hindi_ok = False


def _drive_with_retries(client, item: Item) -> Run:
    """Google's free tier often answers 503/504 under load: wait and retry the file (calls
    that already succeeded replay from this run's recordings, so only failures are redone)."""
    for attempt in range(3):
        run = _drive(client, item)
        transient = [p for p in run.problems if _TRANSIENT.search(p) and not _QUOTA.search(p)]
        if not transient or attempt == 2:
            return run
        print(f"[score] {getattr(client, 'model', '?')}: {item.name[:2]} hit a temporary "
              f"Google error; retrying in 30s ({attempt + 1}/2)", flush=True)
        time.sleep(30)
    return run


def _score_model(model: str, *, client=None) -> Score:
    """Score one model live (its own throwaway recordings), or, with `client`, score
    whatever the committed recordings say (replay, no key)."""
    from pipeline.m3_extract.llm_client import LLMClient

    score = Score(model)
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as fx:
        client = client or LLMClient(fx, live=True, model=model, race=False)
        for n, item in enumerate(i for i in _items() if i.key is not None):
            print(f"[score] {model}: {item.name}", flush=True)
            try:
                run = _drive_with_retries(client, item)
            except Exception as exc:  # noqa: BLE001
                score.error = f"{type(exc).__name__}: {str(exc)[:160]}"
                break
            if any(_QUOTA.search(p) for p in run.problems):
                if n == 0 and client.live_calls == 0:
                    score.error = "not available on this key (free-tier quota is 0)"
                else:
                    score.incomplete = f"free-tier quota ran out after {n} of 8 files"
                break
            if n == 0 and client.live and client.live_calls == 0 and run.problems:
                score.error = run.problems[0][:200]  # model not on this key, or still down
                break
            _score_run(score, item, run)
    score.seconds = time.monotonic() - t0
    return score


def _pick(scores: list[Score]) -> tuple[list[str], str]:
    ok = [s for s in scores if s.ran]
    if not ok:
        return [], "no model ran"
    best_caught = max(s.caught for s in ok)
    best_chat = max(s.chat_ok for s in ok)
    keep = [s.model for s in ok if s.caught == best_caught and not s.false_alarms
            and s.chat_ok >= best_chat - 1 and s.hindi_ok]
    rule = (f"kept: every fault the best model caught ({best_caught}), no false alarm, chat "
            f"within 1 of the best ({best_chat}), Hindi numbers intact")
    if not keep:
        best = max(ok, key=lambda s: (s.caught - 2 * len(s.false_alarms), s.chat_ok))
        keep, rule = [best.model], "no model met every bar; kept the single best scorer"
    return keep, rule


def cmd_score(models: list[str], *, from_recordings: bool = False) -> int:
    from pipeline.m3_extract.llm_client import RACE_FILE, LLMClient

    if from_recordings:  # re-score the committed race recordings: no key, no API calls
        client = LLMClient(live=False, race=True)
        print(f"[score] from recordings: {client.describe()}")
        scores = [_score_model(", ".join(client.race_models), client=client)]
        keep = list(client.race_models)
        rule = json.loads(RACE_FILE.read_text("utf-8")).get("rule", "")
    else:
        print(f"[score] {len(models)} models in parallel: {', '.join(models)}")
        with ThreadPoolExecutor(max_workers=len(models)) as pool:
            scores = list(pool.map(_score_model, models))
        keep, rule = _pick(scores)
    lines = ["# Gemini model race: which models are allowed in", "",
             f"Scored by `make score-models` on {time.strftime('%Y-%m-%d')} against the "
             "answer keys in `tests/testpack/` (8 synthetic claims, 10 chat questions).", "",
             "| Model | AI-only faults caught | False alarms | Chat correct | Hindi | Time | "
             "In race |", "|---|---|---|---|---|---|---|"]
    for s in scores:
        if s.error or s.incomplete:
            why = s.incomplete or f"did not run: {s.error}"
            lines.append(f"| `{s.model}` | {why} | | | | | no |")
            continue
        lines.append(
            f"| `{s.model}` | {s.caught}/{s.faults}"
            + (f" (missed {', '.join(s.missed)})" if s.missed else "")
            + f" | {len(s.false_alarms)}" + (f" ({', '.join(s.false_alarms)})"
                                             if s.false_alarms else "")
            + f" | {s.chat_ok}/{s.chat_total} | {'ok' if s.hindi_ok else 'changed numbers'}"
            + f" | {s.seconds / 60:.1f} min | "
            + f"{'**yes**' if any(m in keep for m in s.model.split(', ')) else 'no'} |")
    lines += ["", f"Rule: {rule}.", "",
              "Faults are scored only where the rules can't catch them (ICU days, missing "
              "scan report, name spelling variants); the agents are built not to duplicate "
              "rule items. False alarms count agent items shown on the clean files (05, 06).",
              "",
              "Chat answers are checked with simple keyword rules (see `CHAT_06` in "
              "`scripts/testpack.py`), so read a borderline row before trusting it."]
    report = "\n".join(lines) + "\n"
    (REPO / "evals" / "MODEL_RACE.md").write_text(report, encoding="utf-8")
    if from_recordings:
        print("\n" + report)
        return 0
    RACE_FILE.write_text(json.dumps({"models": keep, "rule": rule,
                                     "scored": time.strftime("%Y-%m-%d")}, indent=1) + "\n",
                         encoding="utf-8")
    print("\n" + report)
    print(f"[score] race models -> {RACE_FILE.relative_to(REPO)}: {keep}")
    return 0 if keep else 1


def cmd_record_or_check(live: bool) -> int:
    from pipeline.m3_extract.llm_client import LLMClient

    mode = "record" if live else "check"
    client = LLMClient(live=live, race=True)
    if live and not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        sys.exit("[record] needs GEMINI_API_KEY in .env")
    if not client.racing:
        sys.exit(f"[{mode}] no race models configured: run `make score-models` first")
    print(f"[{mode}] {client.describe()}")
    failed = 0
    for item in _items():
        run = _drive(client, item)
        status = "ok" if not run.problems else f"{len(run.problems)} missing"
        print(f"[{mode}] {item.name}: {status}  ({client.answers_summary() or 'no AI calls'})")
        for p in run.problems:
            print(f"    - {p}")
        failed += bool(run.problems)
    print(f"[{mode}] {client.calls} AI replies, {client.live_calls} recorded live. "
          + ("All test-pack AI features replay without a key." if not failed
             else f"{failed} file(s) incomplete."))
    if failed and not live:
        print("Run `make record-testpack` once with GEMINI_API_KEY in .env, then commit "
              "tests/fixtures/llm/.")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    # Windows: a log file or pipe defaults to the legacy code page, which can't print Hindi.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("score")
    sc.add_argument("--models", default=",".join(CANDIDATES))
    sc.add_argument("--from-recordings", action="store_true",
                    help="re-score the committed race recordings (no key, no API calls)")
    sub.add_parser("record")
    sub.add_parser("check")
    args = ap.parse_args(argv)
    if args.cmd == "score":
        return cmd_score([m.strip() for m in args.models.split(",") if m.strip()],
                         from_recordings=args.from_recordings)
    return cmd_record_or_check(live=args.cmd == "record")


if __name__ == "__main__":
    raise SystemExit(main())
