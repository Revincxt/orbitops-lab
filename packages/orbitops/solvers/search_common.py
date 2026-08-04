"""Shared genome, decoder, budget, and ranking for stochastic search."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from orbitops.domain.models import Metrics, Scenario, Schedule, ValidationReport
from orbitops.domain.objective import ObjectiveScore, score_schedule
from orbitops.simulation.validator import validate_schedule
from orbitops.solvers.common import best_feasible_insertion, empty_schedule


@dataclass(frozen=True, slots=True)
class Genome:
    """Full task priority order plus the subset eligible for decoding."""

    order: tuple[str, ...]
    active: frozenset[str]

    def __post_init__(self) -> None:
        if len(self.order) != len(set(self.order)):
            raise ValueError("genome order must not contain duplicate task IDs")
        if not self.active.issubset(self.order):
            raise ValueError("active task IDs must be present in genome order")


@dataclass(frozen=True, slots=True)
class EvaluatedGenome:
    genome: Genome
    schedule: Schedule
    validation: ValidationReport
    metrics: Metrics
    score: ObjectiveScore


class EvaluationBudgetExceeded(RuntimeError):
    pass


class GenomeEvaluator:
    """Decode unique genomes under a deterministic evaluation budget."""

    def __init__(
        self,
        scenario: Scenario,
        *,
        solver_name: str,
        seed: int,
        budget: int,
    ) -> None:
        if budget <= 0:
            raise ValueError("evaluation budget must be positive")
        self.scenario = scenario
        self.solver_name = solver_name
        self.seed = seed
        self.budget = budget
        self.evaluations = 0
        self._cache: dict[Genome, EvaluatedGenome] = {}
        self._task_by_id = {task.task_id: task for task in scenario.tasks}
        self._expected_ids = frozenset(self._task_by_id)

    def evaluate(self, genome: Genome) -> EvaluatedGenome:
        cached = self._cache.get(genome)
        if cached is not None:
            return cached
        if self.evaluations >= self.budget:
            raise EvaluationBudgetExceeded
        if len(genome.order) != len(self._expected_ids) or set(genome.order) != self._expected_ids:
            raise ValueError("genome order must contain every scenario task exactly once")

        schedule = empty_schedule(self.scenario, self.solver_name, self.seed)
        for task_id in genome.order:
            if task_id not in genome.active:
                continue
            candidate = best_feasible_insertion(
                self.scenario,
                schedule,
                self._task_by_id[task_id],
            )
            if candidate is not None:
                schedule = candidate.schedule

        validation = validate_schedule(self.scenario, schedule)
        if not validation.is_feasible or validation.simulation is None:
            raise RuntimeError("genome decoder violated the shared feasibility contract")
        metrics = score_schedule(
            self.scenario,
            schedule,
            total_slew_time_s=validation.simulation.total_slew_time_s,
        )
        evaluated = EvaluatedGenome(
            genome=genome,
            schedule=schedule,
            validation=validation,
            metrics=metrics,
            score=ObjectiveScore.from_metrics(metrics),
        )
        self._cache[genome] = evaluated
        self.evaluations += 1
        return evaluated


def genome_from_schedule(scenario: Scenario, schedule: Schedule) -> Genome:
    scheduled_ids = tuple(assignment.task_id for assignment in schedule.tasks)
    scheduled_set = frozenset(scheduled_ids)
    remaining = sorted(
        (task for task in scenario.tasks if task.task_id not in scheduled_set),
        key=lambda task: (-task.priority_value, task.task_id),
    )
    return Genome(
        order=(*scheduled_ids, *(task.task_id for task in remaining)),
        active=scheduled_set,
    )


def random_genome(scenario: Scenario, rng: random.Random) -> Genome:
    order = [task.task_id for task in scenario.tasks]
    rng.shuffle(order)
    active = frozenset(task_id for task_id in order if rng.random() < 0.7)
    if order and not active:
        active = frozenset({rng.choice(order)})
    return Genome(order=tuple(order), active=active)


def evaluated_key(
    evaluated: EvaluatedGenome,
) -> tuple[float, int, float, tuple[tuple[float, str, str], ...]]:
    schedule_key = tuple(
        (assignment.start_s, assignment.task_id, assignment.window_id)
        for assignment in evaluated.schedule.tasks
    )
    return (
        -evaluated.score.total_value,
        -evaluated.score.completed_tasks,
        -evaluated.score.negative_slew_time_s,
        schedule_key,
    )


def is_better(candidate: EvaluatedGenome, incumbent: EvaluatedGenome) -> bool:
    return candidate.score > incumbent.score


def convergence_point(evaluation: int, evaluated: EvaluatedGenome) -> dict[str, float | int]:
    return {
        "evaluation": evaluation,
        "total_value": evaluated.metrics.total_value,
        "completed_tasks": evaluated.metrics.completed_tasks,
        "total_slew_time_s": evaluated.metrics.total_slew_time_s,
    }


def attach_search_metadata(
    schedule: Schedule,
    *,
    metadata: dict[str, Any],
) -> Schedule:
    merged = dict(schedule.metadata)
    merged.update(metadata)
    return schedule.model_copy(update={"metadata": merged})
