"""Shared dominance rule and bookkeeping for exact tiny-instance search."""

from __future__ import annotations

from dataclasses import dataclass

from orbitops.domain.models import (
    ObservationTask,
    Scenario,
    Schedule,
    TaskAssignment,
    ValidationReport,
)
from orbitops.domain.objective import ObjectiveScore, score_schedule
from orbitops.domain.transitions import recharge_energy_wh, required_slew_time_s
from orbitops.simulation.validator import validate_schedule
from orbitops.solvers.common import EPSILON, InsertionCandidate


@dataclass(slots=True)
class SearchStats:
    nodes_expanded: int = 0
    feasible_extensions: int = 0
    branches_pruned: int = 0
    timed_out: bool = False


def schedule_key(schedule: Schedule) -> tuple[tuple[float, str, str], ...]:
    return tuple(
        (assignment.start_s, assignment.task_id, assignment.window_id)
        for assignment in schedule.tasks
    )


def validated_score(
    scenario: Scenario,
    schedule: Schedule,
    validation: ValidationReport,
) -> ObjectiveScore:
    if not validation.is_feasible or validation.simulation is None:
        raise ValueError("exact search can score only validator-approved schedules")
    metrics = score_schedule(
        scenario,
        schedule,
        total_slew_time_s=validation.simulation.total_slew_time_s,
    )
    return ObjectiveScore.from_metrics(metrics)


def is_better_solution(
    score: ObjectiveScore,
    schedule: Schedule,
    incumbent_score: ObjectiveScore,
    incumbent_schedule: Schedule,
) -> bool:
    if score != incumbent_score:
        return score > incumbent_score
    return schedule_key(schedule) < schedule_key(incumbent_schedule)


def feasible_appends(
    scenario: Scenario,
    schedule: Schedule,
    task: ObservationTask,
    *,
    validation: ValidationReport | None = None,
) -> tuple[InsertionCandidate, ...]:
    """Append a task at its earliest resource-feasible time in each window.

    For a fixed task order and selected windows, an earlier feasible execution
    leaves at least as much time and energy for every later task under the v0.1
    constant-recharge model. This dominance rule makes the continuous-time
    exact search finite without a time grid.
    """

    if any(assignment.task_id == task.task_id for assignment in schedule.tasks):
        return ()

    validation = validation or validate_schedule(scenario, schedule)
    if not validation.is_feasible or validation.simulation is None:
        raise ValueError("feasible_appends requires a valid partial schedule")

    satellite = scenario.satellite
    if task.storage_cost_gb > satellite.storage_capacity_gb + EPSILON:
        return ()
    if task.energy_cost_wh > satellite.energy_capacity_wh + EPSILON:
        return ()

    if validation.simulation.tasks:
        previous_trace = validation.simulation.tasks[-1]
        previous_task = next(
            candidate for candidate in scenario.tasks if candidate.task_id == previous_trace.task_id
        )
        current_time_s = previous_trace.end_s
        current_energy_wh = previous_trace.energy_after_wh
        current_storage_gb = previous_trace.storage_after_gb
        current_attitude_deg = previous_task.required_attitude_deg
    else:
        current_time_s = scenario.horizon_start_s
        current_energy_wh = satellite.initial_energy_wh
        current_storage_gb = satellite.initial_storage_gb
        current_attitude_deg = satellite.initial_attitude_deg

    if current_storage_gb + task.storage_cost_gb > satellite.storage_capacity_gb + EPSILON:
        return ()

    transition_ready_s = current_time_s + required_slew_time_s(
        satellite,
        current_attitude_deg,
        task.required_attitude_deg,
    )
    candidates: list[InsertionCandidate] = []
    seen: set[tuple[float, str]] = set()

    for window in sorted(task.visibility_windows, key=lambda item: (item.start_s, item.window_id)):
        start_s = max(window.start_s, transition_ready_s, scenario.horizon_start_s)
        idle_s = start_s - current_time_s
        energy_at_end_wh = recharge_energy_wh(
            satellite,
            recharge_energy_wh(satellite, current_energy_wh, idle_s),
            task.duration_s,
        )
        if energy_at_end_wh + EPSILON < task.energy_cost_wh:
            if satellite.recharge_rate_w <= 0.0:
                continue
            deficit_wh = task.energy_cost_wh - energy_at_end_wh
            start_s += deficit_wh * 3600.0 / satellite.recharge_rate_w

        end_s = start_s + task.duration_s
        if end_s > window.end_s + EPSILON or end_s > scenario.horizon_end_s + EPSILON:
            continue

        identity = (round(start_s, 12), window.window_id)
        if identity in seen:
            continue
        seen.add(identity)

        assignment = TaskAssignment(
            task_id=task.task_id,
            start_s=start_s,
            window_id=window.window_id,
        )
        candidate_schedule = schedule.model_copy(update={"tasks": (*schedule.tasks, assignment)})
        candidate_validation = validate_schedule(scenario, candidate_schedule)
        if candidate_validation.is_feasible:
            candidates.append(
                InsertionCandidate(
                    schedule=candidate_schedule,
                    validation=candidate_validation,
                    inserted=assignment,
                )
            )

    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (
                candidate.inserted.start_s,
                candidate.inserted.window_id,
            ),
        )
    )


def attach_search_metadata(
    schedule: Schedule,
    *,
    stats: SearchStats,
    max_tasks: int,
) -> Schedule:
    metadata = dict(schedule.metadata)
    metadata.update(
        {
            "nodes_expanded": stats.nodes_expanded,
            "feasible_extensions": stats.feasible_extensions,
            "branches_pruned": stats.branches_pruned,
            "timed_out": stats.timed_out,
            "complete_search": not stats.timed_out,
            "optimality_proven": not stats.timed_out,
            "max_supported_tasks": max_tasks,
        }
    )
    return schedule.model_copy(update={"metadata": metadata})
