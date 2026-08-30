from pathlib import Path

import pytest
from orbitops import Scenario
from orbitops.solvers import (
    advanced_solvers,
    available_solvers,
    baseline_solvers,
    exact_solvers,
    get_solver,
)

PROJECT_ROOT = Path(__file__).parents[2]
SCENARIO_PATH = PROJECT_ROOT / "scenarios" / "examples" / "demo.json"
EXPECTED_BASELINES = (
    "greedy-deadline",
    "greedy-density",
    "greedy-insertion",
    "greedy-value",
    "random-feasible",
)
EXPECTED_EXACT = ("branch-and-bound", "brute-force")
EXPECTED_ADVANCED = ("genetic", "local-search", "q-learning", "q-policy-only")
EXPECTED_ALL = (
    "branch-and-bound",
    "brute-force",
    "genetic",
    "greedy-deadline",
    "greedy-density",
    "greedy-insertion",
    "greedy-value",
    "local-search",
    "q-learning",
    "q-policy-only",
    "random-feasible",
)


def test_registry_has_stable_solver_names() -> None:
    assert baseline_solvers() == EXPECTED_BASELINES
    assert exact_solvers() == EXPECTED_EXACT
    assert advanced_solvers() == EXPECTED_ADVANCED
    assert available_solvers() == EXPECTED_ALL


def test_registry_passes_search_evaluation_budget() -> None:
    solver = get_solver("local-search", seed=9, evaluation_budget=73)

    assert solver.config.seed == 9
    assert solver.config.evaluation_budget == 73


@pytest.mark.parametrize("solver_name", EXPECTED_BASELINES)
def test_all_baselines_solve_demo_feasibly(solver_name: str) -> None:
    scenario = Scenario.from_json(SCENARIO_PATH)

    result = get_solver(solver_name, seed=42).solve(scenario)

    assert result.validation.is_feasible
    assert result.schedule.solver_name == solver_name
    assert result.metrics.total_value == 226.0
    assert result.metrics.completed_tasks == 3


@pytest.mark.parametrize("solver_name", EXPECTED_BASELINES)
def test_fixed_seed_reproduces_schedule_and_metrics(solver_name: str) -> None:
    scenario = Scenario.from_json(SCENARIO_PATH)
    solver = get_solver(solver_name, seed=73)

    first = solver.solve(scenario)
    second = solver.solve(scenario)

    assert first.schedule == second.schedule
    assert first.metrics == second.metrics


def test_unknown_solver_has_actionable_error() -> None:
    with pytest.raises(ValueError, match=r"unknown solver.*greedy-insertion"):
        get_solver("does-not-exist")
