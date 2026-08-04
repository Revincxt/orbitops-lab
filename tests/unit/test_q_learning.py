from pathlib import Path
from typing import Any

import orbitops.learning.trainer as trainer_module
import pytest
from orbitops import Scenario
from orbitops.domain.objective import ObjectiveScore
from orbitops.learning import (
    FEATURE_NAMES,
    LinearQPolicy,
    QLearningConfig,
    rollout_policy,
    train_policy,
)
from orbitops.solvers import get_solver

from tests.factories import make_seeded_scenario

PROJECT_ROOT = Path(__file__).parents[2]
SCENARIO_PATH = PROJECT_ROOT / "scenarios" / "examples" / "demo.json"


def test_q_learning_is_feasible_budgeted_and_reproducible() -> None:
    scenario = make_seeded_scenario(17, task_count=8)
    first = get_solver("q-learning", seed=73, evaluation_budget=24).solve(scenario)
    second = get_solver("q-learning", seed=73, evaluation_budget=24).solve(scenario)

    assert first.validation.is_feasible
    assert first.schedule == second.schedule
    assert first.metrics == second.metrics
    assert first.schedule.metadata["evaluations"] == 24
    assert first.schedule.metadata["episodes_completed"] == 24
    assert first.schedule.metadata["transitions"] > 0
    assert len(first.schedule.metadata["training_trace"]) == 24
    assert len(first.schedule.metadata["model"]["weights"]) == len(FEATURE_NAMES)


def test_q_learning_retains_greedy_initializer_as_objective_lower_bound() -> None:
    scenario = make_seeded_scenario(21, task_count=10)
    greedy = get_solver("greedy-insertion", seed=9).solve(scenario)
    learned = get_solver("q-learning", seed=9, evaluation_budget=30).solve(scenario)

    assert ObjectiveScore.from_metrics(learned.metrics) >= ObjectiveScore.from_metrics(
        greedy.metrics
    )
    assert learned.schedule.metadata["incumbent_initializer"] == "greedy-insertion"


def test_q_learning_honors_soft_time_limit() -> None:
    scenario = Scenario.from_json(SCENARIO_PATH)

    result = get_solver(
        "q-learning",
        seed=0,
        evaluation_budget=100,
        time_limit_s=0.000001,
    ).solve(scenario)

    assert result.validation.is_feasible
    assert result.schedule.metadata["timed_out"] is True
    assert result.schedule.metadata["stop_reason"] == "time_limit"
    assert result.schedule.metadata["evaluations"] <= 100


def test_training_can_stop_cleanly_between_environment_actions(monkeypatch: Any) -> None:
    scenario = Scenario.from_json(SCENARIO_PATH)
    clock = iter((0.0, 2.0))
    monkeypatch.setattr(trainer_module, "perf_counter", lambda: next(clock))

    outcome = train_policy(
        scenario,
        seed=0,
        config=QLearningConfig(episodes=3),
        started_at=0.0,
        time_limit_s=1.0,
    )

    assert outcome.timed_out is True
    assert outcome.stop_reason == "time_limit"
    assert outcome.episodes_started == 1
    assert outcome.episodes_completed == 0
    assert outcome.transitions == 0


def test_q_learning_stops_terminal_empty_scenario_after_one_episode() -> None:
    scenario = make_seeded_scenario(4, task_count=0)

    result = get_solver("q-learning", seed=4, evaluation_budget=20).solve(scenario)

    assert result.validation.is_feasible
    assert result.schedule.metadata["episodes_completed"] == 1
    assert result.schedule.metadata["transitions"] == 0
    assert result.schedule.metadata["stop_reason"] == "no_feasible_actions"


def test_saved_policy_replays_only_on_fingerprint_matched_scenario() -> None:
    scenario = Scenario.from_json(SCENARIO_PATH)
    trained = get_solver("q-learning", seed=42, evaluation_budget=12).solve(scenario)
    policy = LinearQPolicy.model_validate(trained.schedule.metadata["model"])

    replay = rollout_policy(scenario, policy)

    assert replay.validation.is_feasible
    assert replay.schedule.solver_name == "q-learning-policy"
    assert replay.schedule.metadata["policy_replay"] is True

    changed = scenario.model_copy(update={"name": "Fingerprint mismatch"})
    with pytest.raises(ValueError, match="fingerprint"):
        rollout_policy(changed, policy)

    unsupported = policy.model_copy(
        update={"feature_names": ("unsupported", *policy.feature_names[1:])}
    )
    with pytest.raises(ValueError, match="feature contract"):
        rollout_policy(scenario, unsupported)


def test_saved_policy_rejects_different_scenario_id_first() -> None:
    scenario = Scenario.from_json(SCENARIO_PATH)
    trained = get_solver("q-learning", seed=2, evaluation_budget=2).solve(scenario)
    policy = LinearQPolicy.model_validate(trained.schedule.metadata["model"])
    different = scenario.model_copy(update={"scenario_id": "different"})

    with pytest.raises(ValueError, match="scenario_id"):
        rollout_policy(different, policy)
