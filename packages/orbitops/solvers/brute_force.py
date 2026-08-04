"""Exhaustive exact solver for tiny OrbitOps scenarios."""

from __future__ import annotations

from time import perf_counter

from orbitops.domain.models import ObservationTask, Scenario, Schedule, SolveResult
from orbitops.domain.objective import ObjectiveScore
from orbitops.simulation.validator import validate_schedule
from orbitops.solvers.base import BaseSolver
from orbitops.solvers.common import build_solve_result, empty_schedule
from orbitops.solvers.exact_common import (
    SearchStats,
    attach_search_metadata,
    feasible_appends,
    is_better_solution,
    validated_score,
)


class BruteForceSolver(BaseSolver):
    """Enumerate every feasible task order and visibility-window choice."""

    name = "brute-force"
    max_tasks = 10

    def solve(self, scenario: Scenario) -> SolveResult:
        if len(scenario.tasks) > self.max_tasks:
            raise ValueError(
                f"{self.name} supports at most {self.max_tasks} tasks; "
                f"received {len(scenario.tasks)}"
            )

        started_at = perf_counter()
        stats = SearchStats()
        initial = empty_schedule(scenario, self.name, self.config.seed)
        initial_validation = validate_schedule(scenario, initial)
        best_schedule = initial
        best_score = validated_score(scenario, initial, initial_validation)

        def visit(
            schedule: Schedule,
            remaining: tuple[ObservationTask, ...],
            score: ObjectiveScore,
        ) -> None:
            nonlocal best_schedule, best_score
            if self._time_limit_reached(started_at):
                stats.timed_out = True
                return

            stats.nodes_expanded += 1
            if is_better_solution(score, schedule, best_score, best_schedule):
                best_schedule = schedule
                best_score = score

            validation = validate_schedule(scenario, schedule)
            for task in sorted(remaining, key=lambda item: item.task_id):
                if self._time_limit_reached(started_at):
                    stats.timed_out = True
                    return
                next_remaining = tuple(
                    candidate for candidate in remaining if candidate.task_id != task.task_id
                )
                for candidate in feasible_appends(
                    scenario,
                    schedule,
                    task,
                    validation=validation,
                ):
                    stats.feasible_extensions += 1
                    visit(
                        candidate.schedule,
                        next_remaining,
                        validated_score(scenario, candidate.schedule, candidate.validation),
                    )
                    if stats.timed_out:
                        return

        visit(initial, scenario.tasks, best_score)
        best_schedule = attach_search_metadata(
            best_schedule,
            stats=stats,
            max_tasks=self.max_tasks,
        )
        return build_solve_result(scenario, best_schedule, started_at=started_at)
