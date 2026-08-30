from pathlib import Path
from time import perf_counter

import pytest
from orbitops import Scenario
from orbitops.learning import FEATURE_NAMES, SchedulingEnvironment

from tests.factories import make_seeded_scenario

PROJECT_ROOT = Path(__file__).parents[2]
SCENARIO_PATH = PROJECT_ROOT / "scenarios" / "examples" / "demo.json"


def test_environment_exposes_feasible_actions_and_bounded_features() -> None:
    scenario = Scenario.from_json(SCENARIO_PATH)
    environment = SchedulingEnvironment(scenario)
    state = environment.reset(solver_name="learning-test", seed=13)

    actions = environment.actions(state)

    assert tuple(action.task.task_id for action in actions) == (
        "obs-hangzhou",
        "obs-shanghai",
        "obs-wuhan",
    )
    for action in actions:
        features = environment.features(state, action)
        assert len(features) == len(FEATURE_NAMES)
        assert all(0.0 <= feature <= 1.0 for feature in features)
        assert environment.reward(state, action) > 0


def test_resource_headroom_is_measured_after_the_plan_not_after_horizon_recharge() -> None:
    scenario = Scenario.from_json(SCENARIO_PATH)
    environment = SchedulingEnvironment(scenario)
    state = environment.reset(solver_name="learning-test", seed=13)
    action = environment.actions(state)[0]
    simulation = action.insertion.validation.simulation
    assert simulation is not None

    features = environment.features(state, action)
    energy_headroom = features[FEATURE_NAMES.index("plan_end_energy_headroom")]
    storage_headroom = features[FEATURE_NAMES.index("plan_end_storage_headroom")]
    terminal_task = simulation.tasks[-1]

    assert energy_headroom == pytest.approx(
        terminal_task.energy_after_wh / scenario.satellite.energy_capacity_wh
    )
    assert storage_headroom == pytest.approx(
        1.0 - terminal_task.storage_after_gb / scenario.satellite.storage_capacity_gb
    )
    assert simulation.final_state.energy_wh >= terminal_task.energy_after_wh


def test_environment_transition_adds_exactly_one_validated_task() -> None:
    scenario = Scenario.from_json(SCENARIO_PATH)
    environment = SchedulingEnvironment(scenario)
    state = environment.reset(solver_name="learning-test", seed=13)
    action = environment.actions(state)[0]

    next_state = environment.transition(state, action)

    assert next_state.validation.is_feasible
    assert len(next_state.schedule.tasks) == 1
    assert action.task.task_id not in next_state.remaining_task_ids
    assert environment.metrics(next_state).completed_tasks == 1
    with pytest.raises(ValueError, match="remaining task"):
        environment.transition(next_state, action)


def test_empty_scenario_is_a_terminal_learning_state() -> None:
    scenario = make_seeded_scenario(8, task_count=0)
    environment = SchedulingEnvironment(scenario)
    state = environment.reset(solver_name="learning-test", seed=8)

    assert environment.actions(state) == ()
    assert environment.metrics(state).total_value == 0
    assert environment.metrics(state).completed_tasks == 0


def test_action_enumeration_honors_an_expired_absolute_deadline() -> None:
    scenario = Scenario.from_json(SCENARIO_PATH)
    environment = SchedulingEnvironment(scenario)
    state = environment.reset(solver_name="learning-test", seed=13)

    assert environment.actions(state, deadline_at=perf_counter() - 1.0) == ()
