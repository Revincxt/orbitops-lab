"""Benchmark execution, aggregation, and reproducibility fingerprints."""

from __future__ import annotations

import hashlib
import json
import platform
from collections import defaultdict
from collections.abc import Iterable
from importlib.metadata import PackageNotFoundError, version
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
    ScenarioDescriptor,
    SolverSummary,
)
from orbitops.domain.models import Metrics, Scenario, SolveResult
from orbitops.domain.objective import ObjectiveScore
from orbitops.solvers.registry import available_solvers, get_solver


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
    result: SolveResult,
) -> BenchmarkRunRecord:
    metadata = result.schedule.metadata
    evaluations = metadata.get("evaluations")
    stop_reason = metadata.get("stop_reason")
    return BenchmarkRunRecord(
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
    runtime_s: float,
    error: Exception,
) -> BenchmarkRunRecord:
    return BenchmarkRunRecord(
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
    """Rank solvers on feasibility, normalized value, and objective tie-breakers."""

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
        for run in feasible:
            assert run.metrics is not None
            scenario_seed_values[run.scenario_id].append(run.metrics.total_value)
        seed_stddevs = [
            pstdev(values) if len(values) >= 2 else 0.0 for values in scenario_seed_values.values()
        ]
        unranked.append(
            SolverSummary(
                rank=1,
                solver_name=solver_name,
                run_count=len(solver_runs),
                feasible_count=len(feasible),
                feasible_rate=len(feasible) / len(solver_runs),
                mean_value_ratio=_mean_or_none(value_ratio[run.run_id] for run in feasible),
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


def _fingerprint(
    spec: BenchmarkSpec,
    scenarios: tuple[ScenarioDescriptor, ...],
    runs: tuple[BenchmarkRunRecord, ...],
) -> str:
    run_payloads: list[dict[str, Any]] = []
    for run in runs:
        payload = run.model_dump(mode="json", exclude={"runtime_s"})
        run_payloads.append(payload)
    payload = {
        "spec": spec.model_dump(mode="json"),
        "scenarios": [scenario.model_dump(mode="json") for scenario in scenarios],
        "runs": run_payloads,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def run_benchmark(spec: BenchmarkSpec) -> BenchmarkReport:
    """Execute every configured scenario/solver/seed tuple in stable order."""

    unknown = sorted(set(spec.solvers) - set(available_solvers()))
    if unknown:
        choices = ", ".join(available_solvers())
        raise ValueError(f"unknown benchmark solvers {unknown!r}; choose from: {choices}")

    generated = generate_scenarios(spec)
    records: list[BenchmarkRunRecord] = []
    for scenario, descriptor in generated:
        for solver_name in spec.solvers:
            for algorithm_seed in spec.algorithm_seeds:
                started_at = perf_counter()
                try:
                    result = get_solver(
                        solver_name,
                        seed=algorithm_seed,
                        time_limit_s=spec.time_limit_s,
                        evaluation_budget=spec.evaluation_budget,
                    ).solve(scenario)
                    record = _successful_record(
                        spec,
                        scenario,
                        descriptor,
                        solver_name,
                        algorithm_seed,
                        result,
                    )
                except Exception as error:  # benchmark failures are data, not campaign aborts
                    record = _failed_record(
                        spec,
                        scenario,
                        descriptor,
                        solver_name,
                        algorithm_seed,
                        perf_counter() - started_at,
                        error,
                    )
                records.append(record)

    descriptors = tuple(descriptor for _, descriptor in generated)
    runs = tuple(records)
    return BenchmarkReport(
        spec=spec,
        environment=_environment(),
        scenarios=descriptors,
        runs=runs,
        summaries=summarize_runs(runs),
        reproducibility_fingerprint=_fingerprint(spec, descriptors, runs),
    )
