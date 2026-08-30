"""Exact branch-and-bound solver for small OrbitOps scenarios."""

from __future__ import annotations

from math import fsum
from time import perf_counter

from orbitops.domain.models import (
    ObservationTask,
    Scenario,
    Schedule,
    SolveResult,
    ValidationReport,
)
from orbitops.domain.objective import ObjectiveScore
from orbitops.simulation.validator import validate_schedule
from orbitops.solvers.base import BaseSolver, SolverConfig
from orbitops.solvers.common import build_solve_result, empty_schedule
from orbitops.solvers.exact_common import (
    SearchStats,
    attach_search_metadata,
    feasible_appends,
    is_better_solution,
    validated_score,
)
from orbitops.solvers.greedy import GreedyValueSolver


class BranchAndBoundSolver(BaseSolver):
    """Exact DFS with a lexicographic optimistic objective bound."""

    name = "branch-and-bound"
    max_tasks = 16

    def solve(self, scenario: Scenario) -> SolveResult:
        if len(scenario.tasks) > self.max_tasks:
            raise ValueError(
                f"{self.name} supports at most {self.max_tasks} tasks; "
                f"received {len(scenario.tasks)}"
            )

        started_at = perf_counter()
        deadline_at = self._deadline_at(started_at)
        stats = SearchStats()
        initial = empty_schedule(scenario, self.name, self.config.seed)
        initial_validation = validate_schedule(scenario, initial)
        initial_score = validated_score(scenario, initial, initial_validation)
        total_possible_value = fsum(
            task.priority_value for task in sorted(scenario.tasks, key=lambda item: item.task_id)
        )

        greedy = GreedyValueSolver(
            SolverConfig(seed=self.config.seed),
            deadline_at=deadline_at,
        ).solve(scenario)
        best_schedule = greedy.schedule.model_copy(
            update={"solver_name": self.name, "metadata": {}}
        )
        best_validation = validate_schedule(scenario, best_schedule)
        best_score = validated_score(scenario, best_schedule, best_validation)

        def visit(
            schedule: Schedule,
            validation: ValidationReport,
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

            optimistic = ObjectiveScore(
                total_value=total_possible_value,
                completed_tasks=score.completed_tasks + len(remaining),
                negative_slew_time_s=score.negative_slew_time_s,
            )
            if optimistic <= best_score:
                stats.branches_pruned += 1
                return

            ordered_remaining = sorted(
                remaining,
                key=lambda task: (
                    -task.priority_value,
                    min(window.end_s for window in task.visibility_windows),
                    task.task_id,
                ),
            )
            for task in ordered_remaining:
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
                    deadline_at=deadline_at,
                ):
                    stats.feasible_extensions += 1
                    visit(
                        candidate.schedule,
                        candidate.validation,
                        next_remaining,
                        validated_score(scenario, candidate.schedule, candidate.validation),
                    )
                    if stats.timed_out:
                        return

        if not self._time_limit_reached(started_at):
            visit(initial, initial_validation, scenario.tasks, initial_score)
        else:
            stats.timed_out = True

        best_schedule = attach_search_metadata(
            best_schedule,
            stats=stats,
            max_tasks=self.max_tasks,
        )
        return build_solve_result(scenario, best_schedule, started_at=started_at)
