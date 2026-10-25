"""Eval harness: metrics are computed correctly and the README tables render."""

import pytest

from evals.harness import Report, build_and_score, coverage_accuracy_curve
from evals.report import render_markdown, update_readme


def test_coverage_curve_orders_by_confidence():
    points = [(0.9, True), (0.85, True), (0.4, False), (0.3, False)]
    curve = coverage_accuracy_curve(points, steps=(0.0, 0.5))
    # reviewing the lowest-confidence 50% leaves only the correct high-confidence ones
    reviewed0, _, acc0 = curve[0]
    reviewed50, _, acc50 = curve[1]
    assert reviewed0 == 0.0 and acc0 == 0.5
    assert reviewed50 == 0.5 and acc50 == 1.0


def test_render_markdown_has_expected_sections():
    report = Report(n_claims=1, n_clean=1, classification_correct=6, classification_total=6,
                    exact_by_type={"hospital_bill": [6, 6]},
                    norm_by_type={"hospital_bill": [6, 6]},
                    coverage_points=[(0.95, True), (0.6, False)],
                    source_counts={"rule": 50}, latencies=[0.25])
    md = render_markdown(report)
    assert "Document classification" in md
    assert "Field extraction" in md
    assert "Coverage" in md or "coverage" in md
    assert "Hybrid unit economics" in md


def test_update_readme_between_markers(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("intro\n<!-- BENCHMARK:START -->\nold\n<!-- BENCHMARK:END -->\ntail\n")
    report = Report(n_claims=1, n_clean=1, latencies=[0.1])
    assert update_readme(report, readme)
    text = readme.read_text()
    assert "old" not in text and "Document classification" in text
    assert text.startswith("intro") and text.rstrip().endswith("tail")


def test_report_separates_seen_and_held_out_families():
    report = Report(n_claims=2, n_clean=1, n_faulty=1, latencies=[0.1],
                    fault_recall={"icu_days_mismatch": [1, 1], "date_mismatch": [1, 1]},
                    fault_recall_rules={"icu_days_mismatch": [0, 1], "date_mismatch": [1, 1]},
                    agent_claims=2)
    md = render_markdown(report)
    assert "icu_days_mismatch ★" in md and "all held-out" in md
    assert "Rules + agents" in md


def test_report_says_when_agents_did_not_run():
    md = render_markdown(Report(n_claims=1, n_clean=1, latencies=[0.1],
                                agent_note="no recorded Claude responses"))
    assert "Agent auditor: not run" in md


def test_conformal_threshold_certifies_the_false_flag_rate():
    from evals.conformal import crc_threshold
    # 19 clean claims: most produce nothing, two produce weak items (0.3, 0.55)
    scores = [[] for _ in range(17)] + [[0.3], [0.55]]
    # alpha=0.1, n=19: one shown false item gives bound 19/20*(1/19) + 1/20 = 0.10 -> allowed,
    # so only the 0.3 item must be held back
    cert = crc_threshold(scores, alpha=0.1)
    assert cert["feasible"] and 0.3 < cert["threshold"] <= 0.31
    assert cert["risk_bound"] <= 0.1
    # a stricter alpha forces both held back
    strict = crc_threshold(scores, alpha=0.08)
    assert 0.55 < strict["threshold"] <= 0.56 and strict["empirical_risk"] == 0
    assert not crc_threshold(scores[:5], alpha=0.1)["feasible"]   # too few claims


@pytest.mark.slow
def test_end_to_end_metrics_on_small_set(tmp_path):
    report = build_and_score(seeds_clean=[300], seeds_faulty={201: "inflated_line_item"},
                             out_dir=tmp_path)
    assert report.n_claims == 2 and report.n_clean == 1 and report.n_faulty == 1
    # classification + extraction are exact on clean digital PDFs
    assert report.classification_correct == report.classification_total
    # the injected fault is recalled; the clean file raises no severe review items
    assert report.fault_recall["inflated_line_item"] == [1, 1]
    assert report.clean_false_positives == 0
    assert report.source_counts.get("rule", 0) > 0
