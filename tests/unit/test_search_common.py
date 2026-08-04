from pathlib import Path

import pytest
from orbitops import Scenario
from orbitops.solvers.search_common import (
    EvaluationBudgetExceeded,
    Genome,
    GenomeEvaluator,
)

PROJECT_ROOT = Path(__file__).parents[2]
SCENARIO_PATH = PROJECT_ROOT / "scenarios" / "examples" / "demo.json"


def test_genome_rejects_duplicate_or_unknown_active_ids() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        Genome(order=("a", "a"), active=frozenset({"a"}))
    with pytest.raises(ValueError, match="present in genome order"):
        Genome(order=("a",), active=frozenset({"missing"}))


def test_genome_evaluator_returns_feasible_schedule() -> None:
    scenario = Scenario.from_json(SCENARIO_PATH)
    order = tuple(task.task_id for task in scenario.tasks)
    evaluator = GenomeEvaluator(
        scenario,
        solver_name="test-search",
        seed=42,
        budget=10,
    )

    evaluated = evaluator.evaluate(Genome(order=order, active=frozenset(order)))

    assert evaluated.validation.is_feasible
    assert evaluated.metrics.completed_tasks == 3
    assert evaluator.evaluations == 1


def test_cached_genome_does_not_consume_budget_twice() -> None:
    scenario = Scenario.from_json(SCENARIO_PATH)
    order = tuple(task.task_id for task in scenario.tasks)
    genome = Genome(order=order, active=frozenset(order))
    evaluator = GenomeEvaluator(
        scenario,
        solver_name="test-search",
        seed=42,
        budget=1,
    )

    first = evaluator.evaluate(genome)
    second = evaluator.evaluate(genome)

    assert first is second
    assert evaluator.evaluations == 1
    with pytest.raises(EvaluationBudgetExceeded):
        evaluator.evaluate(Genome(order=tuple(reversed(order)), active=frozenset(order)))


def test_evaluator_rejects_incomplete_order() -> None:
    scenario = Scenario.from_json(SCENARIO_PATH)
    evaluator = GenomeEvaluator(
        scenario,
        solver_name="test-search",
        seed=0,
        budget=2,
    )

    with pytest.raises(ValueError, match="every scenario task"):
        evaluator.evaluate(Genome(order=("obs-shanghai",), active=frozenset()))
