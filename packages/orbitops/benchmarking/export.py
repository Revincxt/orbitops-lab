"""Export benchmark reports, scenarios, CSV tables, and integrity hashes."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from orbitops.benchmarking.generator import generate_scenarios
from orbitops.benchmarking.models import (
    BenchmarkReport,
    BenchmarkRunRecord,
    PairwiseComparison,
    SolverSummary,
)
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
        "run_contract_version": run.run_contract_version or "",
        "run_key": run.run_key or "",
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


def _export_into(report: BenchmarkReport, destination: Path) -> tuple[Path, ...]:
    scenario_dir = destination / "scenarios"
    scenario_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    report_path = destination / "report.json"
    _write_json(report_path, report.model_dump(mode="json"))
    written.append(report_path)

    runs_path = destination / "runs.csv"
    run_fields = (
        "run_contract_version",
        "run_key",
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
    summary_fields = (*SolverSummary.model_fields, "report_schema_version")
    _write_csv(
        summary_path,
        summary_fields,
        (
            {**_summary_row(summary), "report_schema_version": report.schema_version}
            for summary in report.summaries
        ),
    )
    written.append(summary_path)

    comparison_path = destination / "comparisons.csv"
    comparison_fields = (*PairwiseComparison.model_fields, "report_schema_version")
    _write_csv(
        comparison_path,
        comparison_fields,
        (
            {
                **comparison.model_dump(mode="json"),
                "report_schema_version": report.schema_version,
            }
            for comparison in report.comparisons
        ),
    )
    written.append(comparison_path)

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
    if manifest_path.is_symlink():
        raise RuntimeError(f"benchmark manifest must not be a symlink: {manifest_path}")
    manifest = {
        "schema_version": "1",
        "artifact_type": "orbitops-benchmark",
        "report_schema_version": report.schema_version,
        "benchmark_id": report.spec.benchmark_id,
        "reproducibility_fingerprint": report.reproducibility_fingerprint,
        "files": {
            path.relative_to(destination).as_posix(): _sha256(path) for path in sorted(written)
        },
    }
    _write_json(manifest_path, manifest)
    written.append(manifest_path)
    return tuple(written)


def _verify_benchmark_artifacts(
    destination: Path,
    *,
    reject_stale: bool,
) -> tuple[Path, ...]:
    if destination.is_symlink() or not destination.is_dir():
        raise RuntimeError(f"benchmark artifact path is not a directory: {destination}")
    manifest_path = destination / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise RuntimeError(f"invalid benchmark manifest {manifest_path}: {error}") from error
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "1":
        raise RuntimeError(f"unsupported benchmark manifest in {manifest_path}")
    artifact_type = manifest.get("artifact_type")
    if artifact_type not in (None, "orbitops-benchmark"):
        raise RuntimeError(f"unrecognized benchmark artifact type in {manifest_path}")
    raw_files = manifest.get("files")
    if not isinstance(raw_files, dict):
        raise RuntimeError(f"benchmark manifest has no file map: {manifest_path}")

    expected_files: dict[str, str] = {}
    for relative, expected_hash in raw_files.items():
        if not isinstance(relative, str) or not isinstance(expected_hash, str):
            raise RuntimeError(f"invalid file entry in benchmark manifest: {manifest_path}")
        relative_path = Path(relative)
        if relative_path == Path(".") or relative_path.is_absolute() or ".." in relative_path.parts:
            raise RuntimeError(f"unsafe file entry {relative!r} in benchmark manifest")
        if len(expected_hash) != 64 or any(
            character not in "0123456789abcdef" for character in expected_hash
        ):
            raise RuntimeError(f"invalid checksum for {relative!r} in benchmark manifest")
        expected_files[relative_path.as_posix()] = expected_hash

    if "report.json" not in expected_files:
        raise RuntimeError(
            f"benchmark manifest does not checksum its typed identity report: {manifest_path}"
        )

    symlinks = [path for path in destination.rglob("*") if path.is_symlink()]
    if symlinks:
        raise RuntimeError(f"benchmark artifact directory contains symlinks: {symlinks}")
    actual_files = {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file() and path != manifest_path
    }
    missing = sorted(set(expected_files) - actual_files)
    stale = sorted(actual_files - set(expected_files))
    if missing or (reject_stale and stale):
        raise RuntimeError(
            f"benchmark artifact file set mismatch; missing={missing}, stale={stale}"
        )

    verified: list[Path] = []
    for relative, expected_hash in sorted(expected_files.items()):
        path = destination / relative
        try:
            actual_hash = _sha256(path)
        except OSError as error:
            raise RuntimeError(f"cannot read benchmark artifact {path}: {error}") from error
        if actual_hash != expected_hash:
            raise RuntimeError(f"benchmark artifact checksum mismatch: {path}")
        verified.append(path)

    report_path = destination / "report.json"
    try:
        report = BenchmarkReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError(f"invalid benchmark report {report_path}: {error}") from error
    manifest_report_schema = manifest.get("report_schema_version")
    if (
        report.spec.benchmark_id != manifest.get("benchmark_id")
        or report.reproducibility_fingerprint != manifest.get("reproducibility_fingerprint")
        or manifest_report_schema not in (None, report.schema_version)
    ):
        raise RuntimeError("benchmark report identity does not match its manifest")
    verified.append(manifest_path)
    return tuple(verified)


def verify_benchmark_artifacts(output_dir: str | Path) -> tuple[Path, ...]:
    """Validate a complete artifact directory and reject missing, changed, or stale files."""

    return _verify_benchmark_artifacts(Path(output_dir), reject_stale=True)


def _validate_replace_target(destination: Path) -> None:
    if destination.is_symlink():
        raise RuntimeError(f"refusing to replace symlinked artifact directory: {destination}")
    if not destination.exists():
        return
    if not destination.is_dir():
        raise RuntimeError(f"benchmark artifact path is not a directory: {destination}")
    if not any(destination.iterdir()):
        return
    try:
        # Permit a fully verified legacy OrbitOps export without ``artifact_type``
        # so v0.1 output directories remain safely replaceable. Extra stale files
        # are allowed here because the replacement intentionally removes them;
        # every manifest-listed file and report identity must still verify.
        _verify_benchmark_artifacts(destination, reject_stale=False)
    except RuntimeError as error:
        raise RuntimeError(
            f"refusing to replace non-artifact or invalid benchmark directory: {destination}"
        ) from error


def export_benchmark(report: BenchmarkReport, output_dir: str | Path) -> tuple[Path, ...]:
    """Stage, verify, and replace one self-contained benchmark artifact directory."""

    destination = Path(output_dir)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _validate_replace_target(destination)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.stage-", dir=destination.parent))
    backup: Path | None = None
    try:
        staged_files = _export_into(report, staging)
        verify_benchmark_artifacts(staging)
        relative_files = tuple(path.relative_to(staging) for path in staged_files)

        if destination.exists():
            backup = Path(
                tempfile.mkdtemp(prefix=f".{destination.name}.backup-", dir=destination.parent)
            )
            backup.rmdir()
            os.replace(destination, backup)
        try:
            os.replace(staging, destination)
        except OSError:
            if backup is not None and backup.exists() and not destination.exists():
                os.replace(backup, destination)
            raise
        if backup is not None:
            shutil.rmtree(backup)
            backup = None
        return tuple(destination / relative for relative in relative_files)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if backup is not None and backup.exists() and not destination.exists():
            os.replace(backup, destination)
