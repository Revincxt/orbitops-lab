"""Deterministic discrete-event simulation for OrbitOps v0.1 schedules."""

from __future__ import annotations

from dataclasses import dataclass

from orbitops.domain.models import (
    ResourceState,
    Scenario,
    Schedule,
    ScheduledTask,
    SimulationResult,
    ValidationIssue,
)
from orbitops.domain.transitions import recharge_energy_wh, required_slew_time_s
from orbitops.simulation.issues import ValidationCode
from orbitops.simulation.resources import execute_task_resources

EPSILON = 1e-9


@dataclass(frozen=True, slots=True)
class SimulationOutcome:
    result: SimulationResult
    issues: tuple[ValidationIssue, ...]


class DiscreteEventSimulator:
    """Compute all derived times and resource states in chronological order."""

    def simulate(self, scenario: Scenario, schedule: Schedule) -> SimulationOutcome:
        satellite = scenario.satellite
        task_by_id = {task.task_id: task for task in scenario.tasks}
        issues: list[ValidationIssue] = []
        trace: list[ScheduledTask] = []

        if schedule.scenario_id != scenario.scenario_id:
            issues.append(
                ValidationIssue(
                    code=ValidationCode.SCENARIO_MISMATCH,
                    message=(
                        f"schedule targets scenario {schedule.scenario_id!r}, "
                        f"but validator loaded {scenario.scenario_id!r}"
                    ),
                )
            )

        initial_state = ResourceState(
            time_s=scenario.horizon_start_s,
            energy_wh=satellite.initial_energy_wh,
            storage_gb=satellite.initial_storage_gb,
            attitude_deg=satellite.initial_attitude_deg,
        )
        current_time_s = initial_state.time_s
        current_energy_wh = initial_state.energy_wh
        current_storage_gb = initial_state.storage_gb
        current_attitude_deg = initial_state.attitude_deg
        previous: ScheduledTask | None = None
        seen_task_ids: set[str] = set()
        total_slew_time_s = 0.0

        ordered_assignments = sorted(
            enumerate(schedule.tasks),
            key=lambda item: (item[1].start_s, item[1].task_id, item[0]),
        )

        for _, assignment in ordered_assignments:
            if assignment.task_id in seen_task_ids:
                issues.append(
                    ValidationIssue(
                        code=ValidationCode.DUPLICATE_TASK,
                        message=f"task {assignment.task_id!r} is scheduled more than once",
                        task_id=assignment.task_id,
                        time_s=assignment.start_s,
                    )
                )
                continue
            seen_task_ids.add(assignment.task_id)

            task = task_by_id.get(assignment.task_id)
            if task is None:
                issues.append(
                    ValidationIssue(
                        code=ValidationCode.UNKNOWN_TASK,
                        message=f"task {assignment.task_id!r} does not exist in the scenario",
                        task_id=assignment.task_id,
                        time_s=assignment.start_s,
                    )
                )
                continue

            end_s = assignment.start_s + task.duration_s
            window = next(
                (
                    candidate
                    for candidate in task.visibility_windows
                    if candidate.window_id == assignment.window_id
                ),
                None,
            )
            if window is None:
                issues.append(
                    ValidationIssue(
                        code=ValidationCode.UNKNOWN_WINDOW,
                        message=(
                            f"window {assignment.window_id!r} is not valid for "
                            f"task {assignment.task_id!r}"
                        ),
                        task_id=assignment.task_id,
                        time_s=assignment.start_s,
                    )
                )
            elif assignment.start_s < window.start_s - EPSILON or end_s > window.end_s + EPSILON:
                issues.append(
                    ValidationIssue(
                        code=ValidationCode.OUTSIDE_WINDOW,
                        message=(
                            f"task {assignment.task_id!r} interval "
                            f"[{assignment.start_s}, {end_s}) is outside window "
                            f"[{window.start_s}, {window.end_s})"
                        ),
                        task_id=assignment.task_id,
                        time_s=assignment.start_s,
                    )
                )

            if (
                assignment.start_s < scenario.horizon_start_s - EPSILON
                or end_s > scenario.horizon_end_s + EPSILON
            ):
                issues.append(
                    ValidationIssue(
                        code=ValidationCode.OUTSIDE_HORIZON,
                        message=(
                            f"task {assignment.task_id!r} interval "
                            f"[{assignment.start_s}, {end_s}) is outside scenario horizon "
                            f"[{scenario.horizon_start_s}, {scenario.horizon_end_s})"
                        ),
                        task_id=assignment.task_id,
                        time_s=assignment.start_s,
                    )
                )

            transition_origin_s = (
                previous.end_s if previous is not None else scenario.horizon_start_s
            )
            available_transition_time_s = max(0.0, assignment.start_s - transition_origin_s)
            slew_time_s = required_slew_time_s(
                satellite,
                current_attitude_deg,
                task.required_attitude_deg,
            )

            if previous is not None and assignment.start_s < previous.end_s - EPSILON:
                issues.append(
                    ValidationIssue(
                        code=ValidationCode.TASK_OVERLAP,
                        message=(
                            f"task {assignment.task_id!r} starts at {assignment.start_s}, "
                            f"before task {previous.task_id!r} ends at {previous.end_s}"
                        ),
                        task_id=assignment.task_id,
                        related_task_id=previous.task_id,
                        time_s=assignment.start_s,
                    )
                )

            if available_transition_time_s + EPSILON < slew_time_s:
                issues.append(
                    ValidationIssue(
                        code=ValidationCode.INSUFFICIENT_SLEW_TIME,
                        message=(
                            f"task {assignment.task_id!r} has "
                            f"{available_transition_time_s:.6g}s for attitude transition, "
                            f"but requires {slew_time_s:.6g}s"
                        ),
                        task_id=assignment.task_id,
                        related_task_id=previous.task_id if previous is not None else None,
                        time_s=assignment.start_s,
                    )
                )

            resources = execute_task_resources(
                satellite,
                task,
                current_energy_wh=current_energy_wh,
                current_storage_gb=current_storage_gb,
                idle_s=max(0.0, assignment.start_s - current_time_s),
            )
            simulated_task = ScheduledTask(
                task_id=assignment.task_id,
                start_s=assignment.start_s,
                end_s=end_s,
                window_id=assignment.window_id,
                previous_task_id=previous.task_id if previous is not None else None,
                slew_time_s=slew_time_s,
                available_transition_time_s=available_transition_time_s,
                energy_before_wh=resources.energy_before_wh,
                energy_after_wh=resources.energy_after_wh,
                storage_before_gb=resources.storage_before_gb,
                storage_after_gb=resources.storage_after_gb,
            )
            trace.append(simulated_task)

            if resources.energy_after_wh < -EPSILON:
                issues.append(
                    ValidationIssue(
                        code=ValidationCode.ENERGY_BELOW_ZERO,
                        message=(
                            f"task {assignment.task_id!r} leaves energy at "
                            f"{resources.energy_after_wh:.6g}Wh"
                        ),
                        task_id=assignment.task_id,
                        time_s=end_s,
                    )
                )
            if resources.storage_after_gb > satellite.storage_capacity_gb + EPSILON:
                issues.append(
                    ValidationIssue(
                        code=ValidationCode.STORAGE_CAPACITY_EXCEEDED,
                        message=(
                            f"task {assignment.task_id!r} raises storage to "
                            f"{resources.storage_after_gb:.6g}GB, above capacity "
                            f"{satellite.storage_capacity_gb:.6g}GB"
                        ),
                        task_id=assignment.task_id,
                        time_s=end_s,
                    )
                )

            current_time_s = max(current_time_s, end_s)
            current_energy_wh = resources.energy_after_wh
            current_storage_gb = resources.storage_after_gb
            current_attitude_deg = task.required_attitude_deg
            total_slew_time_s += slew_time_s
            previous = simulated_task

        final_time_s = max(scenario.horizon_end_s, current_time_s)
        current_energy_wh = recharge_energy_wh(
            satellite,
            current_energy_wh,
            max(0.0, final_time_s - current_time_s),
        )
        final_state = ResourceState(
            time_s=final_time_s,
            energy_wh=current_energy_wh,
            storage_gb=current_storage_gb,
            attitude_deg=current_attitude_deg,
        )
        result = SimulationResult(
            scenario_id=scenario.scenario_id,
            tasks=tuple(trace),
            initial_state=initial_state,
            final_state=final_state,
            total_slew_time_s=total_slew_time_s,
        )
        return SimulationOutcome(result=result, issues=tuple(issues))
