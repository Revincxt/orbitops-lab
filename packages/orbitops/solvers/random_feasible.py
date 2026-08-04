"""Seeded randomized feasibility baseline."""

from __future__ import annotations

import random
from time import perf_counter

from orbitops.domain.models import Scenario, SolveResult
from orbitops.solvers.base import BaseSolver
from orbitops.solvers.common import build_solve_result, empty_schedule, feasible_insertions


class RandomFeasibleSolver(BaseSolver):
    name = "random-feasible"

    def solve(self, scenario: Scenario) -> SolveResult:
        started_at = perf_counter()
        rng = random.Random(self.config.seed)
        schedule = empty_schedule(scenario, self.name, self.config.seed)
        tasks = list(scenario.tasks)
        rng.shuffle(tasks)

        for task in tasks:
            if self._time_limit_reached(started_at):
                break
            candidates = feasible_insertions(scenario, schedule, task)
            if candidates:
                schedule = rng.choice(candidates).schedule

        return build_solve_result(scenario, schedule, started_at=started_at)
