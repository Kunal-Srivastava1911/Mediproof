"""Conformal calibration of the agent verifier's threshold (certified false-flag rate).

Every agent item on a *clean* claim is a false flag by construction. For a threshold λ an
agent item is shown when `verifier_score >= λ`; the loss of a clean claim is 1 if it shows
any agent item. Conformal risk control (Angelopoulos et al., "Conformal Risk Control",
2022) picks the least conservative λ such that

    n/(n+1) · R̂(λ) + 1/(n+1) ≤ α        (loss bounded by 1)

which guarantees, for a new clean claim exchangeable with the calibration set,

    P(the claim shows ≥ 1 agent item) ≤ α.

The guarantee holds for claims drawn like the calibration claims (here: synthetic). On real
files it is an estimate — the README says so.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

_EPS = 1e-6


def crc_threshold(clean_scores: list[list[float]], alpha: float) -> dict:
    """Return the calibrated threshold and its certificate for `alpha`.

    `clean_scores` holds, per calibration clean claim, the verifier scores of every agent item
    the auditor produced on it (an empty list = no agent items).
    """
    n = len(clean_scores)
    if n == 0:
        return {"threshold": None, "feasible": False, "alpha": alpha, "n_calibration": 0,
                "reason": "no calibration claims with agent output"}
    if 1 / (n + 1) > alpha:
        return {"threshold": None, "feasible": False, "alpha": alpha, "n_calibration": n,
                "reason": f"need at least {int(1 / alpha)} calibration claims for alpha={alpha}"}

    def risk(lam: float) -> float:
        return sum(any(s >= lam for s in scores) for scores in clean_scores) / n

    candidates = sorted({0.0} | {round(s + _EPS, 6) for sc in clean_scores for s in sc})
    candidates.append(1.0 + _EPS)  # shows nothing: always feasible once n is large enough
    for lam in candidates:  # ascending: the first that satisfies the bound is least conservative
        r = risk(lam)
        bound = n / (n + 1) * r + 1 / (n + 1)
        if bound <= alpha:
            return {"threshold": round(lam, 6), "feasible": True, "alpha": alpha,
                    "n_calibration": n, "empirical_risk": round(r, 4),
                    "risk_bound": round(bound, 4)}
    raise AssertionError("unreachable: the top candidate has zero risk")


def write_calibration(cert: dict, path: str | Path) -> Path:
    path = Path(path)
    payload = {
        **cert,
        "method": "conformal risk control: P(clean claim shows >= 1 agent item) <= alpha",
        "calibrated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
