from pathlib import Path

import pytest
from orbitops import Scenario, Schedule
from orbitops.simulation.simulator import DiscreteEventSimulator

PROJECT_ROOT = Path(__file__).parents[2]
SCENARIO_PATH = PROJECT_ROOT / "scenarios" / "examples" / "demo.json"
SCHEDULE_PATH = PROJECT_ROOT / "scenarios" / "examples" / "feasible-schedule.json"


def test_demo_schedule_produces_deterministic_trace() -> None:
    scenario = Scenario.from_json(SCENARIO_PATH)
    schedule = Schedule.from_json(SCHEDULE_PATH)

    outcome = DiscreteEventSimulator().simulate(scenario, schedule)

    assert outcome.issues == ()
    assert [task.task_id for task in outcome.result.tasks] == [
        "obs-shanghai",
        "obs-hangzhou",
        "obs-wuhan",
    ]
    assert [task.end_s for task in outcome.result.tasks] == [165.0, 335.0, 690.0]
    assert outcome.result.tasks[0].slew_time_s == pytest.approx(8.8)
    assert outcome.result.tasks[0].energy_before_wh == pytest.approx(902.6666667)
    assert outcome.result.tasks[0].energy_after_wh == pytest.approx(879.6666667)
    assert outcome.result.total_slew_time_s == pytest.approx(48.4)
    assert outcome.result.final_state.energy_wh == pytest.approx(853.0)
    assert outcome.result.final_state.storage_gb == pytest.approx(8.9)
    assert outcome.result.final_state.attitude_deg == 31.0
    assert outcome.result.final_state.time_s == scenario.horizon_end_s


def test_simulator_normalizes_assignment_order() -> None:
    scenario = Scenario.from_json(SCENARIO_PATH)
    schedule = Schedule.from_json(SCHEDULE_PATH)
    reversed_schedule = schedule.model_copy(update={"tasks": tuple(reversed(schedule.tasks))})

    outcome = DiscreteEventSimulator().simulate(scenario, reversed_schedule)

    assert outcome.issues == ()
    assert [task.task_id for task in outcome.result.tasks] == [
        "obs-shanghai",
        "obs-hangzhou",
        "obs-wuhan",
    ]
