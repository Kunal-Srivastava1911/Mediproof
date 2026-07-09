# M4 — Cross-Document Audit Engine (W6)

**In:** the assembled `ClaimFile` (all `Extracted*` docs). **Out:** `list[Finding]`.

Config-driven YAML rule pack; each rule → a `Finding {id, type, severity, evidence refs}`.

**Framing (non-negotiable):** findings are *documentation review items*, never accusations.
No "fraud"/"reject" language. Every finding links its bbox evidence so a human can judge.

**Floor rules (never cut — plan §10a):**
1. patient name / age / gender consistent across all docs (fuzzy match)
2. bill arithmetic re-validation at claim level; duplicate line items
3. prescription ↔ pharmacy-bill line matching

Plus: billed labs have a report present; non-payable consumables flagged; unmatched
medications; drug↔diagnosis plausibility **only** via a small curated high-confidence
mapping (anything outside the set is *not* flagged — no general clinical inference);
tampering signals (PDF metadata, font inconsistency; copy-move is experimental / cut line 2).

**DoD:** per-fault-type precision/recall vs injected ground truth; **false-positive rate on
clean files** reported. This is the MVP floor.
