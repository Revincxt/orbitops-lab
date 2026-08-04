from pathlib import Path

import pytest
from orbitops import Scenario, Schedule, TaskAssignment
from orbitops.simulation.issues import ValidationCode
from orbitops.simulation.validator import validate_schedule

PROJECT_ROOT = Path(__file__).parents[2]
SCENARIO_PATH = PROJECT_ROOT / "scenarios" / "examples" / "demo.json"
SCHEDULE_PATH = PROJECT_ROOT / "scenarios" / "examples" / "feasible-schedule.json"


@pytest.fixture
def scenario() -> Scenario:
    return Scenario.from_json(SCENARIO_PATH)


@pytest.fixture
def feasible_schedule() -> Schedule:
    return Schedule.from_json(SCHEDULE_PATH)


def _codes(scenario: Scenario, schedule: Schedule) -> set[str]:
    return {issue.code for issue in validate_schedule(scenario, schedule).issues}


def test_golden_schedule_is_feasible(
    scenario: Scenario,
    feasible_schedule: Schedule,
) -> None:
    report = validate_schedule(scenario, feasible_schedule)

    assert report.is_feasible
    assert report.issues == ()
    assert report.simulation is not None


@pytest.mark.parametrize(
    ("schedule", "expected_code"),
    [
        (
            Schedule(
                scenario_id="wrong-scenario",
                solver_name="test",
                tasks=(),
            ),
            ValidationCode.SCENARIO_MISMATCH,
        ),
        (
            Schedule(
                scenario_id="demo-001",
                solver_name="test",
                tasks=(TaskAssignment(task_id="missing", start_s=100, window_id="none"),),
            ),
            ValidationCode.UNKNOWN_TASK,
        ),
        (
            Schedule(
                scenario_id="demo-001",
                solver_name="test",
                tasks=(
                    TaskAssignment(task_id="obs-shanghai", start_s=120, window_id="w-shanghai-1"),
                    TaskAssignment(task_id="obs-shanghai", start_s=200, window_id="w-shanghai-1"),
                ),
            ),
            ValidationCode.DUPLICATE_TASK,
        ),
        (
            Schedule(
                scenario_id="demo-001",
                solver_name="test",
                tasks=(TaskAssignment(task_id="obs-shanghai", start_s=120, window_id="missing"),),
            ),
            ValidationCode.UNKNOWN_WINDOW,
        ),
        (
            Schedule(
                scenario_id="demo-001",
                solver_name="test",
                tasks=(
                    TaskAssignment(task_id="obs-shanghai", start_s=20, window_id="w-shanghai-1"),
                ),
            ),
            ValidationCode.OUTSIDE_WINDOW,
        ),
        (
            Schedule(
                scenario_id="demo-001",
                solver_name="test",
                tasks=(TaskAssignment(task_id="obs-wuhan", start_s=1760, window_id="w-wuhan-1"),),
            ),
            ValidationCode.OUTSIDE_HORIZON,
        ),
        (
            Schedule(
                scenario_id="demo-001",
                solver_name="test",
                tasks=(
                    TaskAssignment(task_id="obs-shanghai", start_s=120, window_id="w-shanghai-1"),
                    TaskAssignment(task_id="obs-hangzhou", start_s=130, window_id="w-hangzhou-1"),
                ),
            ),
            ValidationCode.TASK_OVERLAP,
        ),
        (
            Schedule(
                scenario_id="demo-001",
                solver_name="test",
                tasks=(
                    TaskAssignment(task_id="obs-shanghai", start_s=1, window_id="w-shanghai-1"),
                ),
            ),
            ValidationCode.INSUFFICIENT_SLEW_TIME,
        ),
    ],
)
def test_validator_reports_structural_constraint(
    scenario: Scenario,
    schedule: Schedule,
    expected_code: ValidationCode,
) -> None:
    assert expected_code in _codes(scenario, schedule)


def test_validator_reports_energy_underflow(
    scenario: Scenario,
    feasible_schedule: Schedule,
) -> None:
    payload = scenario.model_dump(mode="json")
    payload["tasks"][0]["energy_cost_wh"] = 2000.0
    depleted_scenario = Scenario.model_validate(payload)
    one_task = feasible_schedule.model_copy(update={"tasks": feasible_schedule.tasks[:1]})

    assert ValidationCode.ENERGY_BELOW_ZERO in _codes(depleted_scenario, one_task)


def test_validator_reports_storage_overflow(
    scenario: Scenario,
    feasible_schedule: Schedule,
) -> None:
    payload = scenario.model_dump(mode="json")
    payload["satellite"]["storage_capacity_gb"] = 3.0
    constrained_scenario = Scenario.model_validate(payload)
    one_task = feasible_schedule.model_copy(update={"tasks": feasible_schedule.tasks[:1]})

    assert ValidationCode.STORAGE_CAPACITY_EXCEEDED in _codes(constrained_scenario, one_task)
