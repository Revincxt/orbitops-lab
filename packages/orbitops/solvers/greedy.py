"""Deterministic greedy baselines and global feasible insertion."""

from __future__ import annotations

from abc import abstractmethod
from time import perf_counter

from orbitops.domain.models import ObservationTask, Scenario, SolveResult
from orbitops.domain.objective import score_schedule
from orbitops.solvers.base import BaseSolver
from orbitops.solvers.common import (
    InsertionCandidate,
    best_feasible_insertion,
    build_solve_result,
    empty_schedule,
    feasible_insertions,
)


class OrderedGreedySolver(BaseSolver):
    """Insert tasks in a deterministic policy order."""

    @abstractmethod
    def order_tasks(self, scenario: Scenario) -> list[ObservationTask]:
        """Return the priority order for attempted insertions."""

    def solve(self, scenario: Scenario) -> SolveResult:
        started_at = perf_counter()
        deadline_at = self._deadline_at(started_at)
        schedule = empty_schedule(scenario, self.name, self.config.seed)
        for task in self.order_tasks(scenario):
            if self._time_limit_reached(started_at):
                break
            candidate = best_feasible_insertion(
                scenario,
                schedule,
                task,
                deadline_at=deadline_at,
            )
            if candidate is not None:
                schedule = candidate.schedule
        return build_solve_result(scenario, schedule, started_at=started_at)


class GreedyValueSolver(OrderedGreedySolver):
    name = "greedy-value"

    def order_tasks(self, scenario: Scenario) -> list[ObservationTask]:
        return sorted(scenario.tasks, key=lambda task: (-task.priority_value, task.task_id))


class GreedyDensitySolver(OrderedGreedySolver):
    name = "greedy-density"

    def order_tasks(self, scenario: Scenario) -> list[ObservationTask]:
        return sorted(
            scenario.tasks,
            key=lambda task: (
                -(task.priority_value / task.duration_s),
                -task.priority_value,
                task.task_id,
            ),
        )


class GreedyDeadlineSolver(OrderedGreedySolver):
    name = "greedy-deadline"

    def order_tasks(self, scenario: Scenario) -> list[ObservationTask]:
        return sorted(
            scenario.tasks,
            key=lambda task: (
                min(window.end_s for window in task.visibility_windows),
                -task.priority_value,
                task.task_id,
            ),
        )


def _global_candidate_rank(
    scenario: Scenario,
    candidate: InsertionCandidate,
) -> tuple[float, int, float, str, float, str]:
    simulation = candidate.validation.simulation
    assert simulation is not None
    metrics = score_schedule(
        scenario,
        candidate.schedule,
        total_slew_time_s=simulation.total_slew_time_s,
    )
    return (
        -metrics.total_value,
        -metrics.completed_tasks,
        metrics.total_slew_time_s,
        candidate.inserted.task_id,
        candidate.inserted.start_s,
        candidate.inserted.window_id,
    )


class GreedyInsertionSolver(BaseSolver):
    """Repeatedly choose the best feasible task-and-position insertion."""

    name = "greedy-insertion"

    def solve(self, scenario: Scenario) -> SolveResult:
        started_at = perf_counter()
        deadline_at = self._deadline_at(started_at)
        schedule = empty_schedule(scenario, self.name, self.config.seed)
        remaining = {task.task_id: task for task in scenario.tasks}

        while remaining and not self._time_limit_reached(started_at):
            candidates: list[InsertionCandidate] = []
            for task_id in sorted(remaining):
                if self._time_limit_reached(started_at):
                    break
                candidates.extend(
                    feasible_insertions(
                        scenario,
                        schedule,
                        remaining[task_id],
                        deadline_at=deadline_at,
                    )
                )
            if not candidates:
                break

            best = min(
                candidates,
                key=lambda candidate: _global_candidate_rank(scenario, candidate),
            )
            schedule = best.schedule
            del remaining[best.inserted.task_id]

        return build_solve_result(scenario, schedule, started_at=started_at)
