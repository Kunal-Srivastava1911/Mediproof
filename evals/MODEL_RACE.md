# Gemini model race: which models are allowed in

Re-scored from the committed race recordings (`testpack.py score --from-recordings`) on 2026-10-30 against the answer keys in `tests/testpack/` (8 synthetic claims, 10 chat questions).

| Model | AI-only faults caught | False alarms | Chat correct | Hindi | Time | In race |
|---|---|---|---|---|---|---|
| `gemini-3.5-flash-lite` | 3/5 (missed 02:missing_imaging_report, 08:icu_days_mismatch) | 0 | 8/10 | ok | replayed | **yes** |

## Not in the race yet

The first live scoring run (2026-10-30, free tier) could not score the other candidates fairly:

| Model | Why it isn't scored yet |
|---|---|
| `gemini-3.8-flash` | Google answered 504 (timeout) on its first call; the scorer of that run gave up instead of retrying. It now retries. |
| `gemini-3.6-flash` | Google answered 503 (overloaded) on its first call; same as above. |
| `gemini-3-flash-preview` | Free-tier daily quota ran out after 4 of the 8 files. |
| `gemini-3.1-pro-preview` | Not available on the free tier (quota 0). |

Re-run `make score-models` (or `./run.ps1 score-models`) on a fresh day's quota to add them;
any model that matches or beats the row above joins the race, and `make record-testpack`
then re-records the replies through the full race.


Faults are scored only where the rules can't catch them (ICU days, missing scan report, name spelling variants); the agents are built not to duplicate rule items. False alarms count agent items shown on the clean files (05, 06).

Chat answers are checked with simple keyword rules (see `CHAT_06` in `scripts/testpack.py`), so read a borderline row before trusting it.
