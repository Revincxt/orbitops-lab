from pathlib import Path

from orbitops.benchmarking import run_benchmark
from orbitops.reporting import write_benchmark_html

from tests.factories import make_benchmark_spec


def test_visual_report_is_self_contained_accessible_and_replay_verified(tmp_path: Path) -> None:
    report = run_benchmark(make_benchmark_spec(evaluation_budget=20))
    output = tmp_path / "visual-report.html"

    selection = write_benchmark_html(report, output)
    rendered = output.read_text(encoding="utf-8")

    assert selection.metrics_verified is True
    assert selection.scenario_id == "test-benchmark-tiny-medium-000"
    assert "Algorithm ranking" in rendered
    assert "Performance by difficulty" in rendered
    assert "Paired comparisons" in rendered
    assert "Value ratio mean [scenario-block 95% CI]" in rendered
    assert "Excluded (both failed)" in rendered
    assert "Normalized value gap [scenario-block 95% CI]" in rendered
    assert "excluded, not ties" in rendered
    assert "jointly failed cells tie" not in rendered
    assert "Search convergence" in rendered
    assert "Representative schedule" in rendered
    assert "Replay matches stored metrics" in rendered
    assert rendered.count('role="img"') >= 3
    assert "mobile-data" in rendered
    assert "prefers-color-scheme: dark" in rendered
    assert "<script" not in rendered
    assert "https://" not in rendered
    assert "fetch(" not in rendered
