"""Benchmark execution, aggregation, and reproducibility fingerprints."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import random
import tempfile
from collections import defaultdict
from collections.abc import Iterable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from importlib.metadata import PackageNotFoundError, version
from itertools import combinations
from pathlib import Path
from statistics import fmean, median, pstdev
from time import perf_counter
from typing import Any

from orbitops.benchmarking.generator import GENERATOR_VERSION, generate_scenarios
from orbitops.benchmarking.models import (
    BenchmarkEnvironment,
    BenchmarkReport,
    BenchmarkRunRecord,
    BenchmarkSpec,
    ConvergencePoint,
    PairwiseComparison,
    ScenarioDescriptor,
    SolverSummary,
)
from orbitops.domain.models import Metrics, Scenario, SolveResult
from orbitops.domain.objective import ObjectiveScore
from orbitops.solvers.registry import available_solvers, get_solver

_BOOTSTRAP_SAMPLES = 1_000
_CHECKPOINT_SCHEMA_VERSION = "1"
# Bump whenever solver, objective, simulator, or result semantics can change.
# It prevents a resume after an upgrade from mixing records produced by two
# executable contracts in one apparently homogeneous report.
BENCHMARK_RUN_CONTRACT_VERSION = "2"


def _environment() -> BenchmarkEnvironment:
    try:
        orbitops_version = version("orbitops-lab")
    except PackageNotFoundError:
        orbitops_version = "uninstalled"
    return BenchmarkEnvironment(
        orbitops_version=orbitops_version,
        python_version=platform.python_version(),
        python_implementation=platform.python_implementation(),
        platform_system=platform.system(),
        platform_machine=platform.machine(),
        generator_version=GENERATOR_VERSION,
    )


def _convergence_points(result: SolveResult) -> tuple[ConvergencePoint, ...]:
    raw_points = result.schedule.metadata.get("convergence")
    if isinstance(raw_points, list):
        return tuple(ConvergencePoint.model_validate(point) for point in raw_points)
    evaluations = result.schedule.metadata.get("evaluations", 0)
    evaluation = evaluations if isinstance(evaluations, int) else 0
    return (
        ConvergencePoint(
            evaluation=evaluation,
            total_value=result.metrics.total_value,
            completed_tasks=result.metrics.completed_tasks,
            total_slew_time_s=result.metrics.total_slew_time_s,
        ),
    )


def _successful_record(
    spec: BenchmarkSpec,
    scenario: Scenario,
    descriptor: ScenarioDescriptor,
    solver_name: str,
    algorithm_seed: int,
    run_key: str,
    result: SolveResult,
) -> BenchmarkRunRecord:
    metadata = result.schedule.metadata
    evaluations = metadata.get("evaluations")
    stop_reason = metadata.get("stop_reason")
    return BenchmarkRunRecord(
        run_contract_version=BENCHMARK_RUN_CONTRACT_VERSION,
        run_key=run_key,
        run_id=f"{scenario.scenario_id}:{solver_name}:{algorithm_seed}",
        scenario_id=scenario.scenario_id,
        size=descriptor.size,
        difficulty=descriptor.difficulty,
        instance_index=descriptor.instance_index,
        task_count=len(scenario.tasks),
        solver_name=solver_name,
        algorithm_seed=algorithm_seed,
        evaluation_budget=spec.evaluation_budget,
        feasible=result.validation.is_feasible,
        metrics=result.metrics,
        runtime_s=result.runtime_s,
        evaluations=evaluations if isinstance(evaluations, int) else None,
        stop_reason=stop_reason if isinstance(stop_reason, str) else None,
        convergence=_convergence_points(result),
    )


def _failed_record(
    spec: BenchmarkSpec,
    scenario: Scenario,
    descriptor: ScenarioDescriptor,
    solver_name: str,
    algorithm_seed: int,
    run_key: str,
    runtime_s: float,
    error: Exception,
) -> BenchmarkRunRecord:
    return BenchmarkRunRecord(
        run_contract_version=BENCHMARK_RUN_CONTRACT_VERSION,
        run_key=run_key,
        run_id=f"{scenario.scenario_id}:{solver_name}:{algorithm_seed}",
        scenario_id=scenario.scenario_id,
        size=descriptor.size,
        difficulty=descriptor.difficulty,
        instance_index=descriptor.instance_index,
        task_count=len(scenario.tasks),
        solver_name=solver_name,
        algorithm_seed=algorithm_seed,
        evaluation_budget=spec.evaluation_budget,
        feasible=False,
        runtime_s=runtime_s,
        error=f"{type(error).__name__}: {error}",
    )


def _mean_or_none(values: Iterable[float]) -> float | None:
    materialized = tuple(values)
    return fmean(materialized) if materialized else None


def _score(metrics: Metrics) -> ObjectiveScore:
    return ObjectiveScore.from_metrics(metrics)


def benchmark_run_key(
    spec: BenchmarkSpec,
    descriptor: ScenarioDescriptor,
    solver_name: str,
    algorithm_seed: int,
) -> str:
    """Return a content-addressed key for one independently resumable run."""

    payload = {
        "schema_version": _CHECKPOINT_SCHEMA_VERSION,
        "run_contract_version": BENCHMARK_RUN_CONTRACT_VERSION,
        "scenario_sha256": descriptor.sha256,
        "solver_name": solver_name,
        "algorithm_seed": algorithm_seed,
        "evaluation_budget": spec.evaluation_budget,
        "time_limit_s": spec.time_limit_s,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _scenario_block_mean_ci(
    blocks: Mapping[str, Iterable[float]],
    *,
    seed_material: str,
) -> tuple[float, float, float, int] | None:
    """Return an equal-scenario mean and deterministic block-bootstrap interval.

    Algorithm seeds are repeated measurements inside a scenario. The bootstrap
    therefore resamples scenario means, preserving the scenario as the
    independent experimental unit instead of treating every run as independent.
    """

    scenario_means = tuple(
        fmean(values)
        for scenario_id in sorted(blocks)
        if (values := tuple(sorted(blocks[scenario_id])))
    )
    if not scenario_means:
        return None
    point_estimate = fmean(scenario_means)
    if len(scenario_means) == 1:
        return point_estimate, point_estimate, point_estimate, 1
    seed = int.from_bytes(hashlib.sha256(seed_material.encode()).digest()[:8], "big")
    rng = random.Random(seed)
    count = len(scenario_means)
    replicates = [
        fmean(scenario_means[rng.randrange(count)] for _ in range(count))
        for _ in range(_BOOTSTRAP_SAMPLES)
    ]
    return (
        point_estimate,
        _percentile(replicates, 0.025),
        _percentile(replicates, 0.975),
        count,
    )


def normalized_value_ratios(runs: tuple[BenchmarkRunRecord, ...]) -> dict[str, float]:
    """Return per-run value ratios within each scenario and algorithm seed."""

    by_comparison: dict[tuple[str, int], list[BenchmarkRunRecord]] = defaultdict(list)
    for run in runs:
        by_comparison[(run.scenario_id, run.algorithm_seed)].append(run)

    ratios: dict[str, float] = {}
    for comparison_runs in by_comparison.values():
        feasible = [run for run in comparison_runs if run.feasible and run.metrics is not None]
        if not feasible:
            continue
        best_value = max(run.metrics.total_value for run in feasible if run.metrics is not None)
        for run in feasible:
            assert run.metrics is not None
            ratios[run.run_id] = run.metrics.total_value / best_value if best_value > 0 else 1.0
    return ratios


def summarize_runs(runs: tuple[BenchmarkRunRecord, ...]) -> tuple[SolverSummary, ...]:
    """Rank solvers with scenario-balanced normalized-value evidence."""

    by_solver: dict[str, list[BenchmarkRunRecord]] = defaultdict(list)
    for run in runs:
        by_solver[run.solver_name].append(run)

    value_ratio = normalized_value_ratios(runs)
    best_observed: dict[str, bool] = {}
    by_comparison: dict[tuple[str, int], list[BenchmarkRunRecord]] = defaultdict(list)
    for run in runs:
        by_comparison[(run.scenario_id, run.algorithm_seed)].append(run)
    for comparison_runs in by_comparison.values():
        feasible = [run for run in comparison_runs if run.feasible and run.metrics is not None]
        if not feasible:
            continue
        best_score = max(_score(run.metrics) for run in feasible if run.metrics is not None)
        for run in feasible:
            assert run.metrics is not None
            best_observed[run.run_id] = _score(run.metrics) == best_score

    unranked: list[SolverSummary] = []
    for solver_name, solver_runs in sorted(by_solver.items()):
        feasible = [run for run in solver_runs if run.feasible and run.metrics is not None]
        metrics = [run.metrics for run in feasible if run.metrics is not None]
        scenario_seed_values: dict[str, list[float]] = defaultdict(list)
        value_ratio_blocks: dict[str, list[float]] = defaultdict(list)
        for run in feasible:
            assert run.metrics is not None
            scenario_seed_values[run.scenario_id].append(run.metrics.total_value)
            value_ratio_blocks[run.scenario_id].append(value_ratio[run.run_id])
        seed_stddevs = [
            pstdev(values) if len(values) >= 2 else 0.0 for values in scenario_seed_values.values()
        ]
        value_ratio_evidence = _scenario_block_mean_ci(
            value_ratio_blocks,
            seed_material=f"v2:solver-normalized-value-ratio:{solver_name}",
        )
        unranked.append(
            SolverSummary(
                rank=1,
                solver_name=solver_name,
                run_count=len(solver_runs),
                feasible_count=len(feasible),
                feasible_rate=len(feasible) / len(solver_runs),
                mean_value_ratio=(
                    value_ratio_evidence[0] if value_ratio_evidence is not None else None
                ),
                best_observed_rate=_mean_or_none(
                    float(best_observed[run.run_id]) for run in feasible
                ),
                mean_total_value=_mean_or_none(metric.total_value for metric in metrics),
                median_total_value=(
                    median(metric.total_value for metric in metrics) if metrics else None
                ),
                mean_completed_tasks=_mean_or_none(
                    float(metric.completed_tasks) for metric in metrics
                ),
                mean_total_slew_time_s=_mean_or_none(
                    metric.total_slew_time_s for metric in metrics
                ),
                mean_runtime_s=fmean(run.runtime_s for run in solver_runs),
                mean_seed_value_stddev=_mean_or_none(seed_stddevs),
                value_ratio_ci95_low=(
                    value_ratio_evidence[1] if value_ratio_evidence is not None else None
                ),
                value_ratio_ci95_high=(
                    value_ratio_evidence[2] if value_ratio_evidence is not None else None
                ),
                value_ratio_scenario_count=(
                    value_ratio_evidence[3] if value_ratio_evidence is not None else 0
                ),
            )
        )

    def ranking_key(summary: SolverSummary) -> tuple[float, float, float, float, float, str]:
        mean_slew = summary.mean_total_slew_time_s
        return (
            -summary.feasible_rate,
            -(summary.mean_value_ratio or 0.0),
            -(summary.best_observed_rate or 0.0),
            -(summary.mean_completed_tasks or 0.0),
            mean_slew if mean_slew is not None else float("inf"),
            summary.solver_name,
        )

    ranked = sorted(unranked, key=ranking_key)
    return tuple(
        summary.model_copy(update={"rank": index}) for index, summary in enumerate(ranked, start=1)
    )


def pairwise_comparisons(
    runs: tuple[BenchmarkRunRecord, ...],
) -> tuple[PairwiseComparison, ...]:
    """Compare shared cells and bootstrap normalized gaps by scenario block."""

    by_solver: dict[str, dict[tuple[str, int], BenchmarkRunRecord]] = defaultdict(dict)
    for run in runs:
        cell = (run.scenario_id, run.algorithm_seed)
        if cell in by_solver[run.solver_name]:
            raise ValueError(f"duplicate benchmark run for {run.solver_name!r} and {cell!r}")
        by_solver[run.solver_name][cell] = run

    value_ratio = normalized_value_ratios(runs)
    comparisons: list[PairwiseComparison] = []
    for solver_a, solver_b in combinations(sorted(by_solver), 2):
        cells = sorted(set(by_solver[solver_a]) & set(by_solver[solver_b]))
        if not cells:
            continue
        wins = ties = losses = failed_both = 0
        value_differences: list[float] = []
        normalized_gap_blocks: dict[str, list[float]] = defaultdict(list)
        for cell in cells:
            run_a = by_solver[solver_a][cell]
            run_b = by_solver[solver_b][cell]
            if run_a.feasible != run_b.feasible:
                if run_a.feasible:
                    wins += 1
                else:
                    losses += 1
                continue
            if not run_a.feasible:
                failed_both += 1
                continue
            assert run_a.metrics is not None
            assert run_b.metrics is not None
            score_a = _score(run_a.metrics)
            score_b = _score(run_b.metrics)
            if score_a > score_b:
                wins += 1
            elif score_a < score_b:
                losses += 1
            else:
                ties += 1
            value_differences.append(run_a.metrics.total_value - run_b.metrics.total_value)
            normalized_gap_blocks[cell[0]].append(
                value_ratio[run_a.run_id] - value_ratio[run_b.run_id]
            )

        normalized_gap_evidence = _scenario_block_mean_ci(
            normalized_gap_blocks,
            seed_material=f"v2:paired-normalized-value-gap:{solver_a}:{solver_b}",
        )
        analyzed_count = len(cells) - failed_both
        comparisons.append(
            PairwiseComparison(
                solver_a=solver_a,
                solver_b=solver_b,
                paired_count=len(cells),
                wins_a=wins,
                ties=ties,
                losses_a=losses,
                win_rate_a=(wins / analyzed_count if analyzed_count else None),
                both_feasible_count=len(value_differences),
                mean_total_value_difference=(
                    fmean(value_differences) if value_differences else None
                ),
                failed_both_count=failed_both,
                mean_normalized_value_gap=(
                    normalized_gap_evidence[0] if normalized_gap_evidence is not None else None
                ),
                normalized_value_gap_ci95_low=(
                    normalized_gap_evidence[1] if normalized_gap_evidence is not None else None
                ),
                normalized_value_gap_ci95_high=(
                    normalized_gap_evidence[2] if normalized_gap_evidence is not None else None
                ),
                normalized_value_gap_scenario_count=(
                    normalized_gap_evidence[3] if normalized_gap_evidence is not None else 0
                ),
            )
        )
    return tuple(comparisons)


def _fingerprint(
    spec: BenchmarkSpec,
    scenarios: tuple[ScenarioDescriptor, ...],
    runs: tuple[BenchmarkRunRecord, ...],
) -> str:
    run_payloads: list[dict[str, Any]] = []
    for run in sorted(runs, key=lambda item: (item.run_key or "", item.run_id)):
        payload = run.model_dump(mode="json", exclude={"runtime_s"})
        run_payloads.append(payload)
    payload = {
        "spec": spec.model_dump(mode="json"),
        "scenarios": [
            scenario.model_dump(mode="json")
            for scenario in sorted(scenarios, key=lambda item: item.scenario_id)
        ],
        "runs": run_payloads,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _checkpoint_path(checkpoint_dir: Path, run_key: str) -> Path:
    return checkpoint_dir / f"{run_key}.json"


def _write_checkpoint(
    checkpoint_dir: Path,
    spec: BenchmarkSpec,
    descriptor: ScenarioDescriptor,
    record: BenchmarkRunRecord,
) -> None:
    assert record.run_key is not None
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": _CHECKPOINT_SCHEMA_VERSION,
        "run_contract_version": BENCHMARK_RUN_CONTRACT_VERSION,
        "benchmark_id": spec.benchmark_id,
        "scenario_sha256": descriptor.sha256,
        "run_key": record.run_key,
        "record": record.model_dump(mode="json"),
    }
    destination = _checkpoint_path(checkpoint_dir, record.run_key)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=checkpoint_dir,
            prefix=f".{record.run_key}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _load_checkpoint(
    checkpoint_dir: Path,
    spec: BenchmarkSpec,
    descriptor: ScenarioDescriptor,
    solver_name: str,
    algorithm_seed: int,
    run_key: str,
) -> BenchmarkRunRecord | None:
    path = _checkpoint_path(checkpoint_dir, run_key)
    if not path.exists():
        return None
    if path.is_symlink():
        raise RuntimeError(f"benchmark checkpoint must not be a symlink: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("checkpoint root must be an object")
        expected_header = {
            "schema_version": _CHECKPOINT_SCHEMA_VERSION,
            "run_contract_version": BENCHMARK_RUN_CONTRACT_VERSION,
            "benchmark_id": spec.benchmark_id,
            "scenario_sha256": descriptor.sha256,
            "run_key": run_key,
        }
        actual_header = {name: payload.get(name) for name in expected_header}
        if actual_header != expected_header:
            raise ValueError("checkpoint identity does not match the requested run")
        record = BenchmarkRunRecord.model_validate(payload.get("record"))
    except (json.JSONDecodeError, OSError, ValueError) as error:
        raise RuntimeError(f"invalid benchmark checkpoint {path}: {error}") from error

    expected_run_id = f"{descriptor.scenario_id}:{solver_name}:{algorithm_seed}"
    if (
        record.run_contract_version != BENCHMARK_RUN_CONTRACT_VERSION
        or record.run_key != run_key
        or record.run_id != expected_run_id
        or record.scenario_id != descriptor.scenario_id
        or record.solver_name != solver_name
        or record.algorithm_seed != algorithm_seed
        or record.evaluation_budget != spec.evaluation_budget
    ):
        raise RuntimeError(f"checkpoint record identity mismatch in {path}")
    return record


def _execute_run(
    spec: BenchmarkSpec,
    scenario: Scenario,
    descriptor: ScenarioDescriptor,
    solver_name: str,
    algorithm_seed: int,
    run_key: str,
) -> BenchmarkRunRecord:
    started_at = perf_counter()
    try:
        result = get_solver(
            solver_name,
            seed=algorithm_seed,
            time_limit_s=spec.time_limit_s,
            evaluation_budget=spec.evaluation_budget,
        ).solve(scenario)
        return _successful_record(
            spec,
            scenario,
            descriptor,
            solver_name,
            algorithm_seed,
            run_key,
            result,
        )
    except Exception as error:  # benchmark failures are data, not campaign aborts
        return _failed_record(
            spec,
            scenario,
            descriptor,
            solver_name,
            algorithm_seed,
            run_key,
            perf_counter() - started_at,
            error,
        )


def run_benchmark(
    spec: BenchmarkSpec,
    *,
    checkpoint_dir: str | Path | None = None,
    resume: bool = False,
    workers: int = 1,
    retry_failures: bool = False,
) -> BenchmarkReport:
    """Execute a campaign with deterministic ordering and optional atomic checkpoints."""

    unknown = sorted(set(spec.solvers) - set(available_solvers()))
    if unknown:
        choices = ", ".join(available_solvers())
        raise ValueError(f"unknown benchmark solvers {unknown!r}; choose from: {choices}")
    if workers < 1:
        raise ValueError("benchmark workers must be at least one")
    if workers > 1 and spec.time_limit_s is not None:
        raise ValueError("time-limited benchmark campaigns require workers=1")
    if resume and checkpoint_dir is None:
        raise ValueError("resume requires a checkpoint directory")

    generated = generate_scenarios(spec)
    checkpoint_path = Path(checkpoint_dir) if checkpoint_dir is not None else None
    if checkpoint_path is not None and checkpoint_path.is_symlink():
        raise ValueError(f"benchmark checkpoint directory must not be a symlink: {checkpoint_path}")
    requests: list[tuple[Scenario, ScenarioDescriptor, str, int, str]] = []
    for scenario, descriptor in generated:
        for solver_name in spec.solvers:
            for algorithm_seed in spec.algorithm_seeds:
                run_key = benchmark_run_key(spec, descriptor, solver_name, algorithm_seed)
                requests.append((scenario, descriptor, solver_name, algorithm_seed, run_key))

    records_by_key: dict[str, BenchmarkRunRecord] = {}
    pending: list[tuple[Scenario, ScenarioDescriptor, str, int, str]] = []
    for request in requests:
        _, descriptor, solver_name, algorithm_seed, run_key = request
        restored = None
        if resume and checkpoint_path is not None:
            restored = _load_checkpoint(
                checkpoint_path,
                spec,
                descriptor,
                solver_name,
                algorithm_seed,
                run_key,
            )
        if restored is not None and not (retry_failures and restored.error is not None):
            records_by_key[run_key] = restored
        else:
            pending.append(request)

    def retain(record: BenchmarkRunRecord, descriptor: ScenarioDescriptor) -> None:
        assert record.run_key is not None
        records_by_key[record.run_key] = record
        if checkpoint_path is not None:
            _write_checkpoint(checkpoint_path, spec, descriptor, record)

    if workers == 1:
        for scenario, descriptor, solver_name, algorithm_seed, run_key in pending:
            retain(
                _execute_run(
                    spec,
                    scenario,
                    descriptor,
                    solver_name,
                    algorithm_seed,
                    run_key,
                ),
                descriptor,
            )
    else:
        pool = ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="orbitops-benchmark",
        )
        futures: dict[Future[BenchmarkRunRecord], ScenarioDescriptor] = {}
        try:
            for scenario, descriptor, solver_name, algorithm_seed, run_key in pending:
                future = pool.submit(
                    _execute_run,
                    spec,
                    scenario,
                    descriptor,
                    solver_name,
                    algorithm_seed,
                    run_key,
                )
                futures[future] = descriptor
            for future in as_completed(futures):
                retain(future.result(), futures[future])
        except BaseException:
            # Thread workers cannot be force-killed safely, but queued work must
            # not keep an interrupted campaign running through the whole matrix.
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        else:
            pool.shutdown(wait=True)

    descriptors = tuple(descriptor for _, descriptor in generated)
    runs = tuple(records_by_key[request[-1]] for request in requests)
    return BenchmarkReport(
        spec=spec,
        environment=_environment(),
        scenarios=descriptors,
        runs=runs,
        summaries=summarize_runs(runs),
        comparisons=pairwise_comparisons(runs),
        reproducibility_fingerprint=_fingerprint(spec, descriptors, runs),
    )
