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
