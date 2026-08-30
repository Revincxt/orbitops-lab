"""Per-scenario linear Q-learning solver."""

from __future__ import annotations

from time import perf_counter

from orbitops.domain.models import Scenario, SolveResult
from orbitops.learning import QLearningConfig, train_policy
from orbitops.solvers.base import BaseSolver
from orbitops.solvers.common import build_solve_result


class QLearningSolver(BaseSolver):
    """Train Q-learning while retaining greedy as an explicit incumbent."""

    name = "q-learning"

    def solve(self, scenario: Scenario) -> SolveResult:
        started_at = perf_counter()
        deadline_at = self._deadline_at(started_at)
        outcome = train_policy(
            scenario,
            seed=self.config.seed,
            config=QLearningConfig(episodes=self.config.evaluation_budget),
            started_at=started_at,
            deadline_at=deadline_at,
            solver_name=self.name,
        )
        return build_solve_result(scenario, outcome.schedule, started_at=started_at)


class QPolicyOnlySolver(BaseSolver):
    """Return the selected policy checkpoint, without a greedy fallback."""

    name = "q-policy-only"

    def solve(self, scenario: Scenario) -> SolveResult:
        started_at = perf_counter()
        deadline_at = self._deadline_at(started_at)
        outcome = train_policy(
            scenario,
            seed=self.config.seed,
            config=QLearningConfig(episodes=self.config.evaluation_budget),
            started_at=started_at,
            deadline_at=deadline_at,
            solver_name="q-learning",
        )
        metadata = dict(outcome.schedule.metadata)
        metadata.pop("incumbent_initializer", None)
        returned_solution_mode = (
            "policy-checkpoint-replay"
            if outcome.selected_checkpoint_episode is not None
            else "no-complete-policy-checkpoint"
        )
        metadata.update(
            {
                "algorithm_variant": self.name,
                "returned_solution_mode": returned_solution_mode,
                "hybrid_reference_metrics": outcome.metrics.model_dump(mode="json"),
                "convergence": [dict(point) for point in outcome.policy_convergence],
            }
        )
        schedule = outcome.policy_schedule.model_copy(
            update={
                "solver_name": self.name,
                "seed": self.config.seed,
                "metadata": metadata,
            }
        )
        return build_solve_result(scenario, schedule, started_at=started_at)
