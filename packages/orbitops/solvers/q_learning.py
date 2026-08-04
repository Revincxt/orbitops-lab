"""Per-scenario linear Q-learning solver."""

from __future__ import annotations

from time import perf_counter

from orbitops.domain.models import Scenario, SolveResult
from orbitops.learning import QLearningConfig, train_policy
from orbitops.solvers.base import BaseSolver
from orbitops.solvers.common import build_solve_result


class QLearningSolver(BaseSolver):
    """Train a seeded linear action-value policy for one scheduling scenario."""

    name = "q-learning"

    def solve(self, scenario: Scenario) -> SolveResult:
        started_at = perf_counter()
        outcome = train_policy(
            scenario,
            seed=self.config.seed,
            config=QLearningConfig(episodes=self.config.evaluation_budget),
            started_at=started_at,
            time_limit_s=self.config.time_limit_s,
            solver_name=self.name,
        )
        return build_solve_result(scenario, outcome.schedule, started_at=started_at)
