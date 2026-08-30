from pathlib import Path
from time import perf_counter

import pytest
from orbitops import Scenario
from orbitops.domain.models import Metrics
from orbitops.domain.objective import ObjectiveScore
from orbitops.learning import (
    FEATURE_NAMES,
    LinearQPolicy,
    QLearningConfig,
    rollout_policy,
    train_policy,
)
from orbitops.solvers import get_solver
from orbitops.solvers.base import SolverConfig
from orbitops.solvers.q_learning import QLearningSolver, QPolicyOnlySolver

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
    assert first.schedule.metadata["policy_checkpoints_evaluated"] == 24
    assert first.schedule.metadata["policy_checkpoint_candidates"] == 24
    assert first.schedule.metadata["policy_checkpoint_selection_complete"] is True
    assert [
        point["episode"] for point in first.schedule.metadata["policy_checkpoint_trace"]
    ] == list(range(1, 25))
    selected_episode = first.schedule.metadata["selected_checkpoint_episode"]
    assert isinstance(selected_episode, int)
    assert 1 <= selected_episode <= 24
    assert first.schedule.metadata["model"]["selected_checkpoint_episode"] == selected_episode
    assert first.schedule.metadata["model"]["evaluated_checkpoints"] == 24
    assert len(first.schedule.metadata["model"]["weights"]) == len(FEATURE_NAMES)

    checkpoint_scores = [
        ObjectiveScore.from_metrics(
            Metrics.model_validate(
                {
                    "total_value": point["total_value"],
                    "completed_tasks": point["completed_tasks"],
                    "total_slew_time_s": point["total_slew_time_s"],
                }
            )
        )
        for point in first.schedule.metadata["policy_checkpoint_trace"]
    ]
    selected_score = ObjectiveScore.from_metrics(
        Metrics.model_validate(first.schedule.metadata["policy_checkpoint_metrics"])
    )
    assert selected_score == max(checkpoint_scores)
    selected_point = next(
        point
        for point in first.schedule.metadata["policy_checkpoint_trace"]
        if point["episode"] == selected_episode
    )
    assert (
        selected_point["total_value"]
        == first.schedule.metadata["policy_checkpoint_metrics"]["total_value"]
    )
    assert (
        selected_point["completed_tasks"]
        == first.schedule.metadata["policy_checkpoint_metrics"]["completed_tasks"]
    )
    assert (
        selected_point["total_slew_time_s"]
        == first.schedule.metadata["policy_checkpoint_metrics"]["total_slew_time_s"]
    )


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


@pytest.mark.parametrize("solver_type", (QLearningSolver, QPolicyOnlySolver))
def test_q_solver_honors_an_inherited_absolute_deadline(
    solver_type: type[QLearningSolver] | type[QPolicyOnlySolver],
) -> None:
    scenario = Scenario.from_json(SCENARIO_PATH)
    solver = solver_type(
        SolverConfig(seed=0, evaluation_budget=100),
        deadline_at=perf_counter() - 1.0,
    )

    result = solver.solve(scenario)

    assert result.validation.is_feasible
    assert result.schedule.metadata["timed_out"] is True
    assert result.schedule.metadata["stop_reason"] == "time_limit"
    assert result.schedule.metadata["episodes_started"] == 0
    assert result.schedule.metadata["policy_checkpoints_evaluated"] == 0
    assert result.schedule.metadata["policy_checkpoint_selection_complete"] is True
    assert result.schedule.metadata["policy_checkpoint_complete"] is False
    assert result.schedule.metadata["returned_solution_mode"] == (
        "greedy-incumbent-plus-training"
        if solver_type is QLearningSolver
        else "no-complete-policy-checkpoint"
    )


def test_training_stops_cleanly_when_absolute_deadline_is_already_expired() -> None:
    scenario = Scenario.from_json(SCENARIO_PATH)

    outcome = train_policy(
        scenario,
        seed=0,
        config=QLearningConfig(episodes=3),
        deadline_at=perf_counter() - 1.0,
    )

    assert outcome.timed_out is True
    assert outcome.stop_reason == "time_limit"
    assert outcome.episodes_started == 0
    assert outcome.episodes_completed == 0
    assert outcome.transitions == 0
    assert outcome.policy_checkpoints_evaluated == 0
    assert outcome.selected_checkpoint_episode is None


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
    assert (
        replay.metrics.model_dump(mode="json")
        == trained.schedule.metadata["policy_checkpoint_metrics"]
    )

    changed = scenario.model_copy(update={"name": "Fingerprint mismatch"})
    with pytest.raises(ValueError, match="fingerprint"):
        rollout_policy(changed, policy)

    unsupported = policy.model_copy(
        update={"feature_names": ("unsupported", *policy.feature_names[1:])}
    )
    with pytest.raises(ValueError, match="feature contract"):
        rollout_policy(scenario, unsupported)


def test_saved_policy_replay_honors_an_expired_absolute_deadline() -> None:
    scenario = Scenario.from_json(SCENARIO_PATH)
    trained = get_solver("q-learning", seed=42, evaluation_budget=2).solve(scenario)
    policy = LinearQPolicy.model_validate(trained.schedule.metadata["model"])

    replay = rollout_policy(scenario, policy, deadline_at=perf_counter() - 1.0)

    assert replay.validation.is_feasible
    assert replay.schedule.tasks == ()
    assert replay.schedule.metadata["policy_replay_complete"] is False
    assert replay.schedule.metadata["timed_out"] is True
    assert replay.schedule.metadata["stop_reason"] == "time_limit"


def test_saved_policy_rejects_an_artifact_without_an_evaluated_checkpoint() -> None:
    scenario = Scenario.from_json(SCENARIO_PATH)
    trained = get_solver("q-learning", seed=42, evaluation_budget=2).solve(scenario)
    payload = dict(trained.schedule.metadata["model"])
    payload.update(selected_checkpoint_episode=None, evaluated_checkpoints=0)
    incomplete = LinearQPolicy.model_validate(payload)

    with pytest.raises(ValueError, match="does not contain an evaluated checkpoint"):
        rollout_policy(scenario, incomplete)


def test_saved_policy_rejects_different_scenario_id_first() -> None:
    scenario = Scenario.from_json(SCENARIO_PATH)
    trained = get_solver("q-learning", seed=2, evaluation_budget=2).solve(scenario)
    policy = LinearQPolicy.model_validate(trained.schedule.metadata["model"])
    different = scenario.model_copy(update={"scenario_id": "different"})

    with pytest.raises(ValueError, match="scenario_id"):
        rollout_policy(different, policy)


def test_policy_only_solver_reports_replayable_policy_without_hybrid_fallback() -> None:
    scenario = make_seeded_scenario(31, task_count=8)

    result = get_solver("q-policy-only", seed=5, evaluation_budget=12).solve(scenario)

    assert result.validation.is_feasible
    assert result.schedule.solver_name == "q-policy-only"
    assert result.schedule.metadata["algorithm_variant"] == "q-policy-only"
    assert result.schedule.metadata["returned_solution_mode"] == "policy-checkpoint-replay"
    assert "incumbent_initializer" not in result.schedule.metadata
    assert result.schedule.metadata["convergence"] == result.schedule.metadata["policy_convergence"]
    assert (
        result.metrics.model_dump(mode="json")
        == result.schedule.metadata["policy_checkpoint_metrics"]
    )


def test_hybrid_result_is_never_worse_than_selected_pure_policy_checkpoint() -> None:
    scenario = make_seeded_scenario(38, task_count=8)

    hybrid = get_solver("q-learning", seed=5, evaluation_budget=12).solve(scenario)
    policy_only = get_solver("q-policy-only", seed=5, evaluation_budget=12).solve(scenario)

    assert ObjectiveScore.from_metrics(hybrid.metrics) >= ObjectiveScore.from_metrics(
        policy_only.metrics
    )
