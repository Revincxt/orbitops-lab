import random
from pathlib import Path

import pytest
from orbitops import Scenario, get_solver
from orbitops.solvers.genetic import mutate_genome, order_crossover
from orbitops.solvers.search_common import Genome

PROJECT_ROOT = Path(__file__).parents[2]
SCENARIO_PATH = PROJECT_ROOT / "scenarios" / "examples" / "demo.json"


def test_order_crossover_preserves_permutation_and_activation_contract() -> None:
    first = Genome(order=("a", "b", "c", "d"), active=frozenset({"a", "c"}))
    second = Genome(order=("d", "c", "b", "a"), active=frozenset({"b", "d"}))

    children = order_crossover(first, second, random.Random(42))

    for child in children:
        assert set(child.order) == set(first.order)
        assert len(child.order) == len(set(child.order))
        assert child.active.issubset(child.order)


def test_order_crossover_rejects_incompatible_parents() -> None:
    first = Genome(order=("a", "b"), active=frozenset())
    second = Genome(order=("a", "c"), active=frozenset())

    with pytest.raises(ValueError, match="same task IDs"):
        order_crossover(first, second, random.Random(0))


def test_mutation_preserves_genome_contract() -> None:
    genome = Genome(order=("a", "b", "c", "d"), active=frozenset({"a", "c"}))

    mutated = mutate_genome(genome, random.Random(17), mutation_rate=1.0)

    assert set(mutated.order) == set(genome.order)
    assert len(mutated.order) == len(set(mutated.order))
    assert mutated.active.issubset(mutated.order)


def test_genetic_search_is_feasible_and_reproducible() -> None:
    scenario = Scenario.from_json(SCENARIO_PATH)
    first = get_solver("genetic", seed=42, evaluation_budget=100).solve(scenario)
    second = get_solver("genetic", seed=42, evaluation_budget=100).solve(scenario)

    assert first.validation.is_feasible
    assert first.schedule == second.schedule
    assert first.metrics == second.metrics
    assert first.schedule.metadata["evaluations"] <= 100
    assert first.schedule.metadata["convergence"] == second.schedule.metadata["convergence"]
