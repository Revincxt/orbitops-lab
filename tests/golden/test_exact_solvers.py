import json
from pathlib import Path

import pytest
from orbitops import Scenario
from orbitops.solvers import exact_solvers, get_solver

from tests.factories import make_seeded_scenario

PROJECT_ROOT = Path(__file__).parents[2]
EXPECTED_PATH = PROJECT_ROOT / "tests" / "golden" / "exact-expected.json"
EXPECTED = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("scenario_id", sorted(EXPECTED))
@pytest.mark.parametrize("solver_name", exact_solvers())
def test_exact_solver_matches_hand_verified_optimum(
    scenario_id: str,
    solver_name: str,
) -> None:
    scenario = Scenario.from_json(PROJECT_ROOT / "scenarios" / "tiny" / f"{scenario_id}.json")
    expected = EXPECTED[scenario_id]

    result = get_solver(solver_name, seed=0).solve(scenario)

    assert result.validation.is_feasible
    assert result.metrics.total_value == expected["total_value"]
    assert result.metrics.completed_tasks == expected["completed_tasks"]
    assert {task.task_id for task in result.schedule.tasks} == set(expected["task_ids"])
    assert result.schedule.metadata["complete_search"] is True
    assert result.schedule.metadata["optimality_proven"] is True


@pytest.mark.parametrize("scenario_id", sorted(EXPECTED))
def test_brute_force_and_branch_bound_objectives_match(scenario_id: str) -> None:
    scenario = Scenario.from_json(PROJECT_ROOT / "scenarios" / "tiny" / f"{scenario_id}.json")

    brute_force = get_solver("brute-force").solve(scenario)
    branch_and_bound = get_solver("branch-and-bound").solve(scenario)

    assert branch_and_bound.metrics == brute_force.metrics
    assert (
        branch_and_bound.schedule.metadata["nodes_expanded"]
        <= (brute_force.schedule.metadata["nodes_expanded"])
    )


def test_brute_force_rejects_scenario_above_safe_limit() -> None:
    scenario = make_seeded_scenario(0, task_count=11)

    with pytest.raises(ValueError, match="supports at most 10 tasks"):
        get_solver("brute-force").solve(scenario)
