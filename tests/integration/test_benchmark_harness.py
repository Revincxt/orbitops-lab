import csv
import hashlib
import json
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any

import pytest
from orbitops.benchmarking import (
    BENCHMARK_RUN_CONTRACT_VERSION,
    BenchmarkReport,
    BenchmarkRunRecord,
    export_benchmark,
    run_benchmark,
    verify_benchmark_artifacts,
)
from orbitops.benchmarking import export as export_module
from orbitops.benchmarking import runner as runner_module

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
        "comparisons.csv",
        "convergence.csv",
        "report.html",
        "manifest.json",
    }
    manifest_path = tmp_path / "artifacts" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["artifact_type"] == "orbitops-benchmark"
    assert manifest["report_schema_version"] == "2"
    for relative_path, expected_hash in manifest["files"].items():
        artifact = tmp_path / "artifacts" / relative_path
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == expected_hash
    assert "report.html" in manifest["files"]

    with (tmp_path / "artifacts" / "summary.csv").open(encoding="utf-8", newline="") as handle:
        summary_fields = next(csv.reader(handle))
    assert "value_ratio_ci95_low" in summary_fields
    assert "value_ratio_scenario_count" in summary_fields
    assert summary_fields[-1] == "report_schema_version"

    with (tmp_path / "artifacts" / "comparisons.csv").open(encoding="utf-8", newline="") as handle:
        comparison_fields = next(csv.reader(handle))
    assert "failed_both_count" in comparison_fields
    assert "mean_normalized_value_gap" in comparison_fields
    assert "normalized_value_gap_ci95_low" in comparison_fields
    assert comparison_fields[-1] == "report_schema_version"


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


def test_parallel_execution_has_stable_order_and_fingerprint() -> None:
    spec = make_benchmark_spec(evaluation_budget=20)

    serial = run_benchmark(spec)
    parallel = run_benchmark(spec, workers=3)

    assert [run.run_key for run in serial.runs] == [run.run_key for run in parallel.runs]
    assert _deterministic_outcomes(serial) == _deterministic_outcomes(parallel)
    assert serial.reproducibility_fingerprint == parallel.reproducibility_fingerprint


def test_time_limited_campaign_rejects_parallel_workers() -> None:
    spec = make_benchmark_spec(evaluation_budget=20).model_copy(update={"time_limit_s": 0.1})

    with pytest.raises(ValueError, match="time-limited benchmark campaigns require workers=1"):
        run_benchmark(spec, workers=2)


def test_parallel_interrupt_cancels_pending_futures_without_waiting_for_matrix(
    monkeypatch: Any,
) -> None:
    spec = make_benchmark_spec(evaluation_budget=20)
    reusable = {run.run_key: run for run in run_benchmark(spec).runs}
    release_workers = Event()
    campaign_finished = Event()
    lock = Lock()
    started: list[str] = []
    blocked_done: list[Event] = []
    observed_errors: list[BaseException] = []

    def controlled_execution(*args: object, **kwargs: object) -> BenchmarkRunRecord:
        del kwargs
        run_key = str(args[-1])
        with lock:
            started.append(run_key)
            ordinal = len(started)
        if ordinal == 1:
            raise KeyboardInterrupt
        done = Event()
        with lock:
            blocked_done.append(done)
        try:
            release_workers.wait(timeout=5.0)
            record = reusable[run_key]
            assert record is not None
            return record
        finally:
            done.set()

    monkeypatch.setattr(runner_module, "_execute_run", controlled_execution)

    def run_interrupted_campaign() -> None:
        try:
            run_benchmark(spec, workers=2)
        except BaseException as error:
            observed_errors.append(error)
        finally:
            campaign_finished.set()

    campaign_thread = Thread(target=run_interrupted_campaign)
    campaign_thread.start()
    completed_before_release = campaign_finished.wait(timeout=2.0)
    with lock:
        started_before_release = tuple(started)
        active_events = tuple(blocked_done)
    release_workers.set()
    campaign_thread.join(timeout=5.0)
    for event in active_events:
        assert event.wait(timeout=2.0)

    assert completed_before_release is True
    assert campaign_thread.is_alive() is False
    assert len(started_before_release) < spec.run_count
    assert len(observed_errors) == 1
    assert isinstance(observed_errors[0], KeyboardInterrupt)


def test_resume_reuses_every_atomic_run_checkpoint(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    spec = make_benchmark_spec(evaluation_budget=20)
    checkpoint_dir = tmp_path / "checkpoints"
    first = run_benchmark(spec, checkpoint_dir=checkpoint_dir, workers=2)
    assert len(tuple(checkpoint_dir.glob("*.json"))) == spec.run_count
    assert not tuple(checkpoint_dir.glob("*.tmp"))
    checkpoint_payload = json.loads(next(checkpoint_dir.glob("*.json")).read_text(encoding="utf-8"))
    assert checkpoint_payload["run_contract_version"] == BENCHMARK_RUN_CONTRACT_VERSION
    assert checkpoint_payload["record"]["run_contract_version"] == BENCHMARK_RUN_CONTRACT_VERSION

    def unexpected_execution(*args: object, **kwargs: object) -> object:
        raise AssertionError("a completed checkpoint was executed again")

    monkeypatch.setattr(runner_module, "_execute_run", unexpected_execution)
    resumed = run_benchmark(spec, checkpoint_dir=checkpoint_dir, resume=True, workers=4)

    assert resumed.runs == first.runs
    assert resumed.reproducibility_fingerprint == first.reproducibility_fingerprint


def test_corrupt_checkpoint_fails_closed(tmp_path: Path) -> None:
    spec = make_benchmark_spec(
        solvers=("greedy-insertion",),
        algorithm_seeds=(0,),
        evaluation_budget=20,
    )
    checkpoint_dir = tmp_path / "checkpoints"
    run_benchmark(spec, checkpoint_dir=checkpoint_dir)
    checkpoint = next(checkpoint_dir.glob("*.json"))
    checkpoint.write_text("{broken", encoding="utf-8")

    with pytest.raises(RuntimeError, match="invalid benchmark checkpoint"):
        run_benchmark(spec, checkpoint_dir=checkpoint_dir, resume=True)


def test_checkpoint_from_another_run_contract_is_rejected(tmp_path: Path) -> None:
    spec = make_benchmark_spec(
        solvers=("greedy-insertion",),
        algorithm_seeds=(0,),
        evaluation_budget=20,
    )
    checkpoint_dir = tmp_path / "checkpoints"
    run_benchmark(spec, checkpoint_dir=checkpoint_dir)
    checkpoint = next(checkpoint_dir.glob("*.json"))
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    payload["run_contract_version"] = "1"
    checkpoint.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match="checkpoint identity"):
        run_benchmark(spec, checkpoint_dir=checkpoint_dir, resume=True)


def test_export_is_staged_removes_stale_files_and_verifies(tmp_path: Path) -> None:
    report = run_benchmark(make_benchmark_spec(evaluation_budget=20))
    destination = tmp_path / "artifacts"
    export_benchmark(report, destination)
    stale = destination / "old-result.csv"
    stale.write_text("obsolete\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="stale"):
        verify_benchmark_artifacts(destination)

    export_benchmark(report, destination)

    assert not stale.exists()
    assert {path.name for path in verify_benchmark_artifacts(destination)} >= {
        "report.json",
        "comparisons.csv",
        "manifest.json",
    }


def test_verifier_cross_checks_report_schema_version(tmp_path: Path) -> None:
    report = run_benchmark(make_benchmark_spec(evaluation_budget=20))
    destination = tmp_path / "artifacts"
    export_benchmark(report, destination)
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["report_schema_version"] = "1"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RuntimeError, match="identity does not match"):
        verify_benchmark_artifacts(destination)


def test_failed_staged_export_preserves_previous_artifacts(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    report = run_benchmark(make_benchmark_spec(evaluation_budget=20))
    destination = tmp_path / "artifacts"
    export_benchmark(report, destination)
    previous_report = (destination / "report.json").read_bytes()

    def fail_report(*args: object, **kwargs: object) -> None:
        raise RuntimeError("report rendering failed")

    monkeypatch.setattr(export_module, "write_benchmark_html", fail_report)
    with pytest.raises(RuntimeError, match="report rendering failed"):
        export_benchmark(report, destination)

    assert (destination / "report.json").read_bytes() == previous_report
    verify_benchmark_artifacts(destination)


def test_export_refuses_to_replace_unrelated_nonempty_directory(tmp_path: Path) -> None:
    report = run_benchmark(make_benchmark_spec(evaluation_budget=20))
    destination = tmp_path / "not-an-export"
    destination.mkdir()
    keep = destination / "user-data.txt"
    keep.write_text("keep me\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="refusing to replace non-artifact"):
        export_benchmark(report, destination)

    assert keep.read_text(encoding="utf-8") == "keep me\n"


def test_export_refuses_generic_manifest_and_preserves_directory(tmp_path: Path) -> None:
    report = run_benchmark(make_benchmark_spec(evaluation_budget=20))
    destination = tmp_path / "generic-manifest"
    destination.mkdir()
    manifest = destination / "manifest.json"
    manifest.write_text('{"schema_version":"1"}\n', encoding="utf-8")

    with pytest.raises(RuntimeError, match="refusing to replace non-artifact"):
        export_benchmark(report, destination)

    assert manifest.read_text(encoding="utf-8") == '{"schema_version":"1"}\n'


def test_export_refuses_tampered_prior_artifact_before_replacement(tmp_path: Path) -> None:
    report = run_benchmark(make_benchmark_spec(evaluation_budget=20))
    destination = tmp_path / "artifacts"
    export_benchmark(report, destination)
    runs_path = destination / "runs.csv"
    runs_path.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="refusing to replace non-artifact"):
        export_benchmark(report, destination)

    assert runs_path.read_text(encoding="utf-8") == "tampered\n"


def test_fully_verified_legacy_manifest_remains_replaceable(tmp_path: Path) -> None:
    report = run_benchmark(make_benchmark_spec(evaluation_budget=20))
    destination = tmp_path / "artifacts"
    export_benchmark(report, destination)
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("artifact_type")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    export_benchmark(report, destination)

    replacement = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert replacement["artifact_type"] == "orbitops-benchmark"


def test_legacy_manifest_must_checksum_its_identity_report(tmp_path: Path) -> None:
    report = run_benchmark(make_benchmark_spec(evaluation_budget=20))
    destination = tmp_path / "artifacts"
    export_benchmark(report, destination)
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("artifact_type")
    manifest["files"].pop("report.json")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RuntimeError, match="refusing to replace non-artifact"):
        export_benchmark(report, destination)

    assert (destination / "report.json").is_file()
