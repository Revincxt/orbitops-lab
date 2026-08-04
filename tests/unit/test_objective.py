from pathlib import Path

import pytest
from orbitops.domain.models import Scenario, Schedule, ScheduledTask
from orbitops.domain.objective import ObjectiveScore, score_schedule

PROJECT_ROOT = Path(__file__).parents[2]
DEMO_PATH = PROJECT_ROOT / "scenarios" / "examples" / "demo.json"


def _scheduled_task(task_id: str, start_s: float, end_s: float, window_id: str) -> ScheduledTask:
    return ScheduledTask(
        task_id=task_id,
        start_s=start_s,
        end_s=end_s,
        window_id=window_id,
        energy_before_wh=900.0,
        energy_after_wh=875.0,
        storage_before_gb=2.0,
        storage_after_gb=4.0,
    )


def test_objective_is_lexicographic() -> None:
    high_value = ObjectiveScore(100.0, 1, -50.0)
    more_tasks = ObjectiveScore(100.0, 2, -80.0)
    less_slew = ObjectiveScore(100.0, 2, -40.0)

    assert more_tasks > high_value
    assert less_slew > more_tasks


def test_score_schedule_uses_scenario_values() -> None:
    scenario = Scenario.from_json(DEMO_PATH)
    schedule = Schedule(
        scenario_id=scenario.scenario_id,
        solver_name="test",
        tasks=(
            _scheduled_task("obs-shanghai", 120.0, 165.0, "w-shanghai-1"),
            _scheduled_task("obs-wuhan", 620.0, 690.0, "w-wuhan-1"),
        ),
    )

    metrics = score_schedule(scenario, schedule, total_slew_time_s=24.5)

    assert metrics.total_value == 154.0
    assert metrics.completed_tasks == 2
    assert metrics.total_slew_time_s == 24.5


def test_unknown_scheduled_task_is_rejected() -> None:
    scenario = Scenario.from_json(DEMO_PATH)
    schedule = Schedule(
        scenario_id=scenario.scenario_id,
        solver_name="test",
        tasks=(_scheduled_task("unknown", 10.0, 20.0, "missing"),),
    )

    with pytest.raises(ValueError, match="unknown task_id"):
        score_schedule(scenario, schedule, total_slew_time_s=0.0)
