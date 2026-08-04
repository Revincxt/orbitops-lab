"""Export benchmark reports, scenarios, CSV tables, and integrity hashes."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from orbitops.benchmarking.generator import generate_scenarios
from orbitops.benchmarking.models import BenchmarkReport, BenchmarkRunRecord, SolverSummary
from orbitops.reporting.benchmark_html import write_benchmark_html


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, fieldnames: tuple[str, ...], rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _run_row(run: BenchmarkRunRecord) -> dict[str, Any]:
    metrics = run.metrics
    return {
        "run_id": run.run_id,
        "scenario_id": run.scenario_id,
        "size": run.size,
        "difficulty": run.difficulty,
        "instance_index": run.instance_index,
        "task_count": run.task_count,
        "solver_name": run.solver_name,
        "algorithm_seed": run.algorithm_seed,
        "evaluation_budget": run.evaluation_budget,
        "feasible": run.feasible,
        "total_value": metrics.total_value if metrics is not None else "",
        "completed_tasks": metrics.completed_tasks if metrics is not None else "",
        "total_slew_time_s": metrics.total_slew_time_s if metrics is not None else "",
        "runtime_s": run.runtime_s,
        "evaluations": run.evaluations if run.evaluations is not None else "",
        "stop_reason": run.stop_reason or "",
        "error": run.error or "",
    }


def _summary_row(summary: SolverSummary) -> dict[str, Any]:
    return summary.model_dump(mode="json", exclude_none=False)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export_benchmark(report: BenchmarkReport, output_dir: str | Path) -> tuple[Path, ...]:
    """Write a self-contained benchmark artifact directory."""

    destination = Path(output_dir)
    scenario_dir = destination / "scenarios"
    scenario_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    report_path = destination / "report.json"
    _write_json(report_path, report.model_dump(mode="json"))
    written.append(report_path)

    runs_path = destination / "runs.csv"
    run_fields = (
        "run_id",
        "scenario_id",
        "size",
        "difficulty",
        "instance_index",
        "task_count",
        "solver_name",
        "algorithm_seed",
        "evaluation_budget",
        "feasible",
        "total_value",
        "completed_tasks",
        "total_slew_time_s",
        "runtime_s",
        "evaluations",
        "stop_reason",
        "error",
    )
    _write_csv(runs_path, run_fields, (_run_row(run) for run in report.runs))
    written.append(runs_path)

    summary_path = destination / "summary.csv"
    summary_fields = tuple(SolverSummary.model_fields)
    _write_csv(
        summary_path,
        summary_fields,
        (_summary_row(summary) for summary in report.summaries),
    )
    written.append(summary_path)

    convergence_path = destination / "convergence.csv"
    convergence_fields = (
        "run_id",
        "scenario_id",
        "size",
        "difficulty",
        "instance_index",
        "solver_name",
        "algorithm_seed",
        "evaluation",
        "total_value",
        "completed_tasks",
        "total_slew_time_s",
    )
    convergence_rows = (
        {
            "run_id": run.run_id,
            "scenario_id": run.scenario_id,
            "size": run.size,
            "difficulty": run.difficulty,
            "instance_index": run.instance_index,
            "solver_name": run.solver_name,
            "algorithm_seed": run.algorithm_seed,
            **point.model_dump(mode="json"),
        }
        for run in report.runs
        for point in run.convergence
    )
    _write_csv(convergence_path, convergence_fields, convergence_rows)
    written.append(convergence_path)

    regenerated = generate_scenarios(report.spec)
    expected_hashes = {descriptor.scenario_id: descriptor.sha256 for descriptor in report.scenarios}
    for scenario, descriptor in regenerated:
        if descriptor.sha256 != expected_hashes.get(descriptor.scenario_id):
            raise RuntimeError(f"scenario fingerprint mismatch for {descriptor.scenario_id!r}")
        scenario_path = scenario_dir / f"{scenario.scenario_id}.json"
        scenario.to_json(scenario_path)
        written.append(scenario_path)

    html_path = destination / "report.html"
    write_benchmark_html(report, html_path)
    written.append(html_path)

    manifest_path = destination / "manifest.json"
    manifest = {
        "schema_version": "1",
        "benchmark_id": report.spec.benchmark_id,
        "reproducibility_fingerprint": report.reproducibility_fingerprint,
        "files": {
            path.relative_to(destination).as_posix(): _sha256(path) for path in sorted(written)
        },
    }
    _write_json(manifest_path, manifest)
    written.append(manifest_path)
    return tuple(written)
