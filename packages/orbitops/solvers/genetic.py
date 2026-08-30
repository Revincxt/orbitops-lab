"""Seeded genetic search with order crossover and feasible decoding."""

from __future__ import annotations

import random
from time import perf_counter

from orbitops.domain.models import Scenario, SolveResult
from orbitops.solvers.base import BaseSolver, SolverConfig
from orbitops.solvers.common import build_solve_result
from orbitops.solvers.greedy import GreedyInsertionSolver
from orbitops.solvers.search_common import (
    EvaluatedGenome,
    EvaluationBudgetExceeded,
    Genome,
    GenomeEvaluator,
    attach_search_metadata,
    convergence_point,
    evaluated_key,
    genome_from_schedule,
    is_better,
    random_genome,
)


def order_crossover(
    first: Genome,
    second: Genome,
    rng: random.Random,
) -> tuple[Genome, Genome]:
    if len(first.order) != len(second.order) or set(first.order) != set(second.order):
        raise ValueError("parent genomes must contain the same task IDs")
    if len(first.order) < 2:
        return first, second

    cut = rng.randrange(1, len(first.order))
    first_prefix = first.order[:cut]
    second_prefix = second.order[:cut]
    first_order = (*first_prefix, *(task for task in second.order if task not in first_prefix))
    second_order = (*second_prefix, *(task for task in first.order if task not in second_prefix))

    first_active: set[str] = set()
    second_active: set[str] = set()
    for task_id in first.order:
        if task_id in (first.active if rng.random() < 0.5 else second.active):
            first_active.add(task_id)
        if task_id in (second.active if rng.random() < 0.5 else first.active):
            second_active.add(task_id)
    return (
        Genome(order=first_order, active=frozenset(first_active)),
        Genome(order=second_order, active=frozenset(second_active)),
    )


def mutate_genome(
    genome: Genome,
    rng: random.Random,
    *,
    mutation_rate: float,
) -> Genome:
    order = list(genome.order)
    active = set(genome.active)
    if len(order) >= 2 and rng.random() < mutation_rate:
        first, second = rng.sample(range(len(order)), 2)
        order[first], order[second] = order[second], order[first]
    if len(order) >= 2 and rng.random() < mutation_rate:
        source, destination = rng.sample(range(len(order)), 2)
        task_id = order.pop(source)
        order.insert(destination, task_id)
    if order and rng.random() < mutation_rate:
        task_id = rng.choice(order)
        if task_id in active:
            active.remove(task_id)
        else:
            active.add(task_id)
    return Genome(order=tuple(order), active=frozenset(active))


def tournament_select(
    population: list[EvaluatedGenome],
    rng: random.Random,
    *,
    tournament_size: int,
) -> EvaluatedGenome:
    contestants = rng.sample(population, min(tournament_size, len(population)))
    return min(contestants, key=evaluated_key)


class GeneticSolver(BaseSolver):
    """Genetic algorithm with elitism and a shared evaluation budget."""

    name = "genetic"
    maximum_population_size = 24
    elite_count = 2
    tournament_size = 3
    crossover_rate = 0.9
    mutation_rate = 0.2

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
        population_by_genome: dict[Genome, EvaluatedGenome] = {best.genome: best}
        target_population_size = min(
            self.maximum_population_size,
            max(4, len(scenario.tasks) * 2),
        )

        value_order = tuple(
            task.task_id
            for task in sorted(
                scenario.tasks,
                key=lambda task: (-task.priority_value, task.task_id),
            )
        )
        value_genome = Genome(order=value_order, active=frozenset(value_order))
        if evaluator.evaluations < evaluator.budget and not evaluator.timed_out:
            value_evaluated = evaluator.evaluate(value_genome)
            population_by_genome[value_genome] = value_evaluated
            if is_better(value_evaluated, best):
                best = value_evaluated
                convergence.append(convergence_point(evaluator.evaluations, best))

        initialization_attempts = 0
        while (
            len(population_by_genome) < target_population_size
            and evaluator.evaluations < evaluator.budget
            and not evaluator.timed_out
            and initialization_attempts < target_population_size * 20
        ):
            initialization_attempts += 1
            genome = random_genome(scenario, rng)
            try:
                evaluated = evaluator.evaluate(genome)
            except EvaluationBudgetExceeded:
                break
            population_by_genome[genome] = evaluated
            if is_better(evaluated, best):
                best = evaluated
                convergence.append(convergence_point(evaluator.evaluations, best))

        population = list(population_by_genome.values())
        generations = 0
        timed_out = evaluator.timed_out or self._time_limit_reached(started_at)

        while evaluator.evaluations < evaluator.budget and len(population) >= 2:
            if evaluator.timed_out or self._time_limit_reached(started_at):
                timed_out = True
                break
            evaluations_before_generation = evaluator.evaluations
            ranked = sorted(population, key=evaluated_key)
            next_population: dict[Genome, EvaluatedGenome] = {
                evaluated.genome: evaluated
                for evaluated in ranked[: min(self.elite_count, len(ranked))]
            }
            generation_attempts = 0

            while (
                len(next_population) < target_population_size
                and evaluator.evaluations < evaluator.budget
                and not evaluator.timed_out
                and generation_attempts < target_population_size * 30
            ):
                if self._time_limit_reached(started_at):
                    timed_out = True
                    break
                generation_attempts += 1
                first_parent = tournament_select(
                    population,
                    rng,
                    tournament_size=self.tournament_size,
                )
                second_parent = tournament_select(
                    population,
                    rng,
                    tournament_size=self.tournament_size,
                )
                if rng.random() < self.crossover_rate:
                    children = order_crossover(first_parent.genome, second_parent.genome, rng)
                else:
                    children = (first_parent.genome, second_parent.genome)

                for child in children:
                    mutated = mutate_genome(
                        child,
                        rng,
                        mutation_rate=self.mutation_rate,
                    )
                    try:
                        evaluated = evaluator.evaluate(mutated)
                    except EvaluationBudgetExceeded:
                        break
                    if evaluator.timed_out:
                        timed_out = True
                        break
                    next_population[mutated] = evaluated
                    if is_better(evaluated, best):
                        best = evaluated
                        convergence.append(convergence_point(evaluator.evaluations, best))
                    if (
                        len(next_population) >= target_population_size
                        or evaluator.evaluations >= evaluator.budget
                    ):
                        break
            if timed_out:
                break
            if evaluator.evaluations == evaluations_before_generation:
                break
            population = list(next_population.values())
            generations += 1

        stop_reason = "time_limit" if timed_out else "search_exhausted"
        if evaluator.evaluations >= evaluator.budget:
            stop_reason = "evaluation_budget"
        schedule = attach_search_metadata(
            best.schedule,
            metadata={
                "evaluation_budget": self.config.evaluation_budget,
                "evaluations": evaluator.evaluations,
                "target_population_size": target_population_size,
                "final_population_size": len(population),
                "generations": generations,
                "elite_count": self.elite_count,
                "tournament_size": self.tournament_size,
                "crossover_rate": self.crossover_rate,
                "mutation_rate": self.mutation_rate,
                "convergence": convergence,
                "timed_out": timed_out,
                "stop_reason": stop_reason,
            },
        )
        return build_solve_result(scenario, schedule, started_at=started_at)
