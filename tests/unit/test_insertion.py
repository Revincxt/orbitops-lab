from pathlib import Path

from orbitops import Scenario
from orbitops.solvers.common import best_feasible_insertion, empty_schedule, feasible_insertions

PROJECT_ROOT = Path(__file__).parents[2]
SCENARIO_PATH = PROJECT_ROOT / "scenarios" / "examples" / "demo.json"


def test_best_insertion_returns_validator_approved_schedule() -> None:
    scenario = Scenario.from_json(SCENARIO_PATH)
    schedule = empty_schedule(scenario, "test", seed=0)

    candidate = best_feasible_insertion(scenario, schedule, scenario.tasks[0])

    assert candidate is not None
    assert candidate.validation.is_feasible
    assert candidate.inserted.start_s == 120.0
    assert candidate.schedule.tasks == (candidate.inserted,)


def test_insertion_refuses_duplicate_task() -> None:
    scenario = Scenario.from_json(SCENARIO_PATH)
    schedule = empty_schedule(scenario, "test", seed=0)
    first = best_feasible_insertion(scenario, schedule, scenario.tasks[0])
    assert first is not None

    assert feasible_insertions(scenario, first.schedule, scenario.tasks[0]) == ()


def test_insertion_refuses_resource_infeasible_task() -> None:
    scenario = Scenario.from_json(SCENARIO_PATH)
    payload = scenario.model_dump(mode="json")
    payload["tasks"][0]["energy_cost_wh"] = 10_000.0
    depleted_scenario = Scenario.model_validate(payload)
    schedule = empty_schedule(depleted_scenario, "test", seed=0)

    assert feasible_insertions(depleted_scenario, schedule, depleted_scenario.tasks[0]) == ()
