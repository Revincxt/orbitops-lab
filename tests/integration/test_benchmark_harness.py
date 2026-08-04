import hashlib
import json
from pathlib import Path

from orbitops.benchmarking import BenchmarkReport, export_benchmark, run_benchmark

from tests.factories import make_benchmark_spec


def _deterministic_outcomes(report: BenchmarkReport) -> list[tuple[object, ...]]:
    return [
        (
            run.run_id,
            run.feasible,
            run.metrics,
            run.evaluations,
            run.convergence,
            run.error,
        )
        for run in report.runs
    ]


def test_benchmark_rerun_has_same_scenarios_objectives_and_fingerprint(tmp_path: Path) -> None:
    spec = make_benchmark_spec(evaluation_budget=30)

    first = run_benchmark(spec)
    second = run_benchmark(spec)

    assert len(first.scenarios) == 1
    assert len(first.runs) == 4
    assert all(run.feasible for run in first.runs)
    assert first.scenarios == second.scenarios
    assert _deterministic_outcomes(first) == _deterministic_outcomes(second)
    assert first.reproducibility_fingerprint == second.reproducibility_fingerprint

    written = export_benchmark(first, tmp_path / "artifacts")
    assert {path.name for path in written} >= {
        "report.json",
        "runs.csv",
        "summary.csv",
        "convergence.csv",
        "report.html",
        "manifest.json",
    }
    manifest_path = tmp_path / "artifacts" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for relative_path, expected_hash in manifest["files"].items():
        artifact = tmp_path / "artifacts" / relative_path
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == expected_hash
    assert "report.html" in manifest["files"]


def test_unsupported_solver_size_is_recorded_without_aborting_campaign() -> None:
    spec = make_benchmark_spec(
        sizes=("medium",),
        solvers=("brute-force",),
        algorithm_seeds=(0,),
    )

    report = run_benchmark(spec)

    assert len(report.runs) == 1
    assert report.runs[0].feasible is False
    assert "supports at most" in (report.runs[0].error or "")
    assert report.summaries[0].feasible_rate == 0.0
