"""Seeded multi-start local search over schedule priority genomes."""

from __future__ import annotations

import random
from time import perf_counter

from orbitops.domain.models import Scenario, SolveResult
from orbitops.solvers.base import BaseSolver, SolverConfig
from orbitops.solvers.common import build_solve_result
from orbitops.solvers.greedy import GreedyInsertionSolver
from orbitops.solvers.search_common import (
    EvaluationBudgetExceeded,
    Genome,
    GenomeEvaluator,
    attach_search_metadata,
    convergence_point,
    genome_from_schedule,
    is_better,
    random_genome,
)

OPERATOR_NAMES = ("activate", "deactivate", "swap", "relocate")


def propose_neighbor(genome: Genome, rng: random.Random) -> tuple[Genome, str] | None:
    order = list(genome.order)
    active = set(genome.active)
    inactive = sorted(set(order) - active)
    operators: list[str] = []
    if inactive:
        operators.append("activate")
    if active:
        operators.append("deactivate")
    if len(order) >= 2:
        operators.extend(("swap", "relocate"))
    if not operators:
        return None

    operator = rng.choice(operators)
    if operator == "activate":
        active.add(rng.choice(inactive))
    elif operator == "deactivate":
        active.remove(rng.choice(sorted(active)))
    elif operator == "swap":
        first, second = rng.sample(range(len(order)), 2)
        order[first], order[second] = order[second], order[first]
    else:
        source, destination = rng.sample(range(len(order)), 2)
        task_id = order.pop(source)
        order.insert(destination, task_id)
    return Genome(order=tuple(order), active=frozenset(active)), operator


class LocalSearchSolver(BaseSolver):
    """Strict-improvement hill climbing with deterministic random restarts."""

    name = "local-search"
    max_restarts = 4

    def solve(self, scenario: Scenario) -> SolveResult:
        started_at = perf_counter()
        deadline_at = self._deadline_at(started_at)
        rng = random.Random(self.config.seed)
        evaluator = GenomeEvaluator(
            scenario,
            solver_name=self.name,
            seed=self.config.seed,
            budget=self.config.evaluation_budget,
            deadline_at=deadline_at,
        )
        greedy = GreedyInsertionSolver(
            SolverConfig(seed=self.config.seed),
            deadline_at=deadline_at,
        ).solve(scenario)
        seed_genome = genome_from_schedule(scenario, greedy.schedule)
        best = evaluator.evaluate(seed_genome)
        convergence = [convergence_point(evaluator.evaluations, best)]
        operator_stats = {
            name: {"attempted": 0, "evaluated": 0, "accepted": 0, "improvements": 0}
            for name in OPERATOR_NAMES
        }
        restarts_started = 0
        total_attempts = 0
        timed_out = evaluator.timed_out or self._time_limit_reached(started_at)
        stagnation_limit = max(20, len(scenario.tasks) * 6)
        maximum_attempts = self.config.evaluation_budget * 8

        for restart in range(self.max_restarts):
            if evaluator.evaluations >= evaluator.budget or total_attempts >= maximum_attempts:
                break
            if evaluator.timed_out or self._time_limit_reached(started_at):
                timed_out = True
                break

            restarts_started += 1
            if restart == 0:
                current = best
            else:
                try:
                    current = evaluator.evaluate(random_genome(scenario, rng))
                except EvaluationBudgetExceeded:
                    break
                if is_better(current, best):
                    best = current
                    convergence.append(convergence_point(evaluator.evaluations, best))

            stagnation = 0
            while stagnation < stagnation_limit and total_attempts < maximum_attempts:
                if evaluator.evaluations >= evaluator.budget:
                    break
                if evaluator.timed_out or self._time_limit_reached(started_at):
                    timed_out = True
                    break
                proposed = propose_neighbor(current.genome, rng)
                if proposed is None:
                    break
                genome, operator = proposed
                total_attempts += 1
                operator_stats[operator]["attempted"] += 1
                evaluations_before = evaluator.evaluations
                try:
                    candidate = evaluator.evaluate(genome)
                except EvaluationBudgetExceeded:
                    break
                if evaluator.timed_out:
                    timed_out = True
                    break
                if evaluator.evaluations > evaluations_before:
                    operator_stats[operator]["evaluated"] += 1

                if is_better(candidate, current):
                    current = candidate
                    operator_stats[operator]["accepted"] += 1
                    stagnation = 0
                else:
                    stagnation += 1

                if is_better(candidate, best):
                    best = candidate
                    operator_stats[operator]["improvements"] += 1
                    convergence.append(convergence_point(evaluator.evaluations, best))
            if timed_out:
                break

        stop_reason = "time_limit" if timed_out else "search_exhausted"
        if evaluator.evaluations >= evaluator.budget:
            stop_reason = "evaluation_budget"
        schedule = attach_search_metadata(
            best.schedule,
            metadata={
                "evaluation_budget": self.config.evaluation_budget,
                "evaluations": evaluator.evaluations,
                "attempts": total_attempts,
                "restarts_started": restarts_started,
                "max_restarts": self.max_restarts,
                "stagnation_limit": stagnation_limit,
                "operator_stats": operator_stats,
                "convergence": convergence,
                "timed_out": timed_out,
                "stop_reason": stop_reason,
            },
        )
        return build_solve_result(scenario, schedule, started_at=started_at)
