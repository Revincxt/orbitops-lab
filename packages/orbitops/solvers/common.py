"""Shared feasibility and result construction for every solver."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from orbitops.domain.models import (
    ObservationTask,
    Scenario,
    Schedule,
    SolveResult,
    TaskAssignment,
    ValidationReport,
)
from orbitops.domain.objective import score_schedule
from orbitops.domain.transitions import required_slew_time_s
from orbitops.simulation.validator import validate_schedule

EPSILON = 1e-9


@dataclass(frozen=True, slots=True)
class InsertionCandidate:
    schedule: Schedule
    validation: ValidationReport
    inserted: TaskAssignment


def empty_schedule(scenario: Scenario, solver_name: str, seed: int) -> Schedule:
    return Schedule(
        scenario_id=scenario.scenario_id,
        solver_name=solver_name,
        seed=seed,
    )


def _assignment_key(assignment: TaskAssignment) -> tuple[float, str, str]:
    return (assignment.start_s, assignment.task_id, assignment.window_id)


def _candidate_starts(earliest_s: float, latest_s: float) -> tuple[float, ...]:
    if latest_s < earliest_s - EPSILON:
        return ()
    if abs(latest_s - earliest_s) <= EPSILON:
        return (earliest_s,)
    return (earliest_s, latest_s)


def feasible_insertions(
    scenario: Scenario,
    schedule: Schedule,
    task: ObservationTask,
) -> tuple[InsertionCandidate, ...]:
    """Enumerate deterministic, validator-approved boundary insertions.

    Each chronological gap contributes its earliest and latest kinematically
    valid start. Testing both boundaries lets a resource-constrained task wait
    for additional charging without introducing a time discretization grid.
    """

    if any(assignment.task_id == task.task_id for assignment in schedule.tasks):
        return ()

    task_by_id = {candidate.task_id: candidate for candidate in scenario.tasks}
    ordered = sorted(schedule.tasks, key=_assignment_key)
    candidates: list[InsertionCandidate] = []
    seen: set[tuple[tuple[str, float, str], ...]] = set()

    for position in range(len(ordered) + 1):
        previous_assignment = ordered[position - 1] if position > 0 else None
        next_assignment = ordered[position] if position < len(ordered) else None
        previous_task = (
            task_by_id[previous_assignment.task_id] if previous_assignment is not None else None
        )
        next_task = task_by_id[next_assignment.task_id] if next_assignment is not None else None

        for window in task.visibility_windows:
            earliest_s = max(window.start_s, scenario.horizon_start_s)
            if previous_assignment is None:
                earliest_s = max(
                    earliest_s,
                    scenario.horizon_start_s
                    + required_slew_time_s(
                        scenario.satellite,
                        scenario.satellite.initial_attitude_deg,
                        task.required_attitude_deg,
                    ),
                )
            else:
                assert previous_task is not None
                previous_end_s = previous_assignment.start_s + previous_task.duration_s
                earliest_s = max(
                    earliest_s,
                    previous_end_s
                    + required_slew_time_s(
                        scenario.satellite,
                        previous_task.required_attitude_deg,
                        task.required_attitude_deg,
                    ),
                )

            latest_s = min(window.end_s, scenario.horizon_end_s) - task.duration_s
            if next_assignment is not None:
                assert next_task is not None
                latest_s = min(
                    latest_s,
                    next_assignment.start_s
                    - task.duration_s
                    - required_slew_time_s(
                        scenario.satellite,
                        task.required_attitude_deg,
                        next_task.required_attitude_deg,
                    ),
                )

            for start_s in _candidate_starts(earliest_s, latest_s):
                inserted = TaskAssignment(
                    task_id=task.task_id,
                    start_s=start_s,
                    window_id=window.window_id,
                )
                assignments = tuple(sorted((*ordered, inserted), key=_assignment_key))
                identity = tuple(
                    (item.task_id, round(item.start_s, 12), item.window_id) for item in assignments
                )
                if identity in seen:
                    continue
                seen.add(identity)

                candidate_schedule = schedule.model_copy(update={"tasks": assignments})
                validation = validate_schedule(scenario, candidate_schedule)
                if validation.is_feasible:
                    candidates.append(
                        InsertionCandidate(
                            schedule=candidate_schedule,
                            validation=validation,
                            inserted=inserted,
                        )
                    )

    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (
                candidate.validation.simulation.total_slew_time_s
                if candidate.validation.simulation is not None
                else float("inf"),
                candidate.inserted.start_s,
                candidate.inserted.window_id,
                tuple(_assignment_key(item) for item in candidate.schedule.tasks),
            ),
        )
    )


def best_feasible_insertion(
    scenario: Scenario,
    schedule: Schedule,
    task: ObservationTask,
) -> InsertionCandidate | None:
    candidates = feasible_insertions(scenario, schedule, task)
    return candidates[0] if candidates else None


def build_solve_result(
    scenario: Scenario,
    schedule: Schedule,
    *,
    started_at: float,
) -> SolveResult:
    """Apply the shared validator and objective to a solver's final schedule."""

    validation = validate_schedule(scenario, schedule)
    if not validation.is_feasible or validation.simulation is None:
        issue_codes = ", ".join(issue.code for issue in validation.issues)
        raise RuntimeError(
            f"solver {schedule.solver_name!r} produced an invalid schedule: {issue_codes}"
        )
    metrics = score_schedule(
        scenario,
        schedule,
        total_slew_time_s=validation.simulation.total_slew_time_s,
    )
    return SolveResult(
        schedule=schedule,
        validation=validation,
        metrics=metrics,
        runtime_s=perf_counter() - started_at,
    )
