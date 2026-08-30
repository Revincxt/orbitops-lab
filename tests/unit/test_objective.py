from pathlib import Path

import pytest
from orbitops.domain.models import Scenario, Schedule, TaskAssignment
from orbitops.domain.objective import ObjectiveScore, score_schedule

PROJECT_ROOT = Path(__file__).parents[2]
DEMO_PATH = PROJECT_ROOT / "scenarios" / "examples" / "demo.json"


def _assignment(task_id: str, start_s: float, window_id: str) -> TaskAssignment:
    return TaskAssignment(
        task_id=task_id,
        start_s=start_s,
        window_id=window_id,
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
            _assignment("obs-shanghai", 120.0, "w-shanghai-1"),
            _assignment("obs-wuhan", 620.0, "w-wuhan-1"),
        ),
    )

    metrics = score_schedule(scenario, schedule, total_slew_time_s=24.5)

    assert metrics.total_value == 154.0
    assert metrics.completed_tasks == 2
    assert metrics.total_slew_time_s == 24.5


def test_score_is_stable_for_every_schedule_order() -> None:
    scenario = Scenario.from_json(DEMO_PATH)
    chronological = Schedule(
        scenario_id=scenario.scenario_id,
        solver_name="test",
        tasks=(
            _assignment("obs-shanghai", 120.0, "w-shanghai-1"),
            _assignment("obs-hangzhou", 390.0, "w-hangzhou-1"),
            _assignment("obs-wuhan", 620.0, "w-wuhan-1"),
        ),
    )
    reverse_payload_order = chronological.model_copy(
        update={"tasks": tuple(reversed(chronological.tasks))}
    )

    assert score_schedule(
        scenario,
        chronological,
        total_slew_time_s=42.0,
    ) == score_schedule(
        scenario,
        reverse_payload_order,
        total_slew_time_s=42.0,
    )


def test_unknown_scheduled_task_is_rejected() -> None:
    scenario = Scenario.from_json(DEMO_PATH)
    schedule = Schedule(
        scenario_id=scenario.scenario_id,
        solver_name="test",
        tasks=(_assignment("unknown", 10.0, "missing"),),
    )

    with pytest.raises(ValueError, match="unknown task_id"):
        score_schedule(scenario, schedule, total_slew_time_s=0.0)


def test_schedule_for_another_scenario_is_rejected() -> None:
    scenario = Scenario.from_json(DEMO_PATH)
    schedule = Schedule(scenario_id="another-scenario", solver_name="test")

    with pytest.raises(ValueError, match="does not match"):
        score_schedule(scenario, schedule, total_slew_time_s=0.0)
