"""Evaluation harness (CLI) — `make eval` regenerates the README benchmark tables. See
README.md.
"""

from evals.harness import Report, build_and_score, coverage_accuracy_curve

__all__ = ["build_and_score", "coverage_accuracy_curve", "Report"]
