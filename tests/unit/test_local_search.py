import random
from pathlib import Path

from orbitops import Scenario, get_solver
from orbitops.solvers.local_search import OPERATOR_NAMES, propose_neighbor
from orbitops.solvers.search_common import Genome

PROJECT_ROOT = Path(__file__).parents[2]
SCENARIO_PATH = PROJECT_ROOT / "scenarios" / "examples" / "demo.json"


def test_neighbor_operators_preserve_genome_contract() -> None:
    rng = random.Random(42)
    genome = Genome(order=("a", "b", "c", "d"), active=frozenset({"a", "b"}))
    observed: set[str] = set()

    for _ in range(200):
        proposed = propose_neighbor(genome, rng)
        assert proposed is not None
        candidate, operator = proposed
        observed.add(operator)
        assert set(candidate.order) == set(genome.order)
        assert len(candidate.order) == len(set(candidate.order))
        assert candidate.active.issubset(candidate.order)

    assert observed == set(OPERATOR_NAMES)


def test_local_search_is_feasible_and_reproducible() -> None:
    scenario = Scenario.from_json(SCENARIO_PATH)
    first = get_solver("local-search", seed=42, evaluation_budget=100).solve(scenario)
    second = get_solver("local-search", seed=42, evaluation_budget=100).solve(scenario)

    assert first.validation.is_feasible
    assert first.schedule == second.schedule
    assert first.metrics == second.metrics
    assert first.schedule.metadata["evaluations"] <= 100
    assert first.schedule.metadata["convergence"] == second.schedule.metadata["convergence"]
