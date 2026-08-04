"""Seeded linear Q-learning and deterministic policy replay."""

from __future__ import annotations

import random
from dataclasses import dataclass
from math import exp, log
from statistics import fmean
from time import perf_counter
from typing import Any

from orbitops.domain.models import Metrics, Scenario, Schedule, SolveResult, ValidationReport
from orbitops.domain.objective import ObjectiveScore
from orbitops.solvers.base import SolverConfig
from orbitops.solvers.common import build_solve_result
from orbitops.solvers.greedy import GreedyInsertionSolver

from .environment import SchedulingAction, SchedulingEnvironment, SchedulingState
from .models import (
    FEATURE_NAMES,
    LinearQPolicy,
    QLearningConfig,
    TrainingPoint,
    scenario_fingerprint,
)

Q_TOLERANCE = 1e-12


@dataclass(frozen=True, slots=True)
class TrainingOutcome:
    schedule: Schedule
    validation: ValidationReport
    metrics: Metrics
    policy: LinearQPolicy
    training_trace: tuple[TrainingPoint, ...]
    convergence: tuple[dict[str, float | int], ...]
    episodes_started: int
    episodes_completed: int
    transitions: int
    timed_out: bool
    stop_reason: str


def _epsilon(config: QLearningConfig, episode: int) -> float:
    if config.episodes == 1 or config.initial_epsilon == 0:
        return config.initial_epsilon
    progress = (episode - 1) / (config.episodes - 1)
    if config.final_epsilon == 0:
        return config.initial_epsilon * (1.0 - progress)
    ratio = config.final_epsilon / config.initial_epsilon
    return config.initial_epsilon * exp(log(ratio) * progress)


def _q_value(weights: list[float] | tuple[float, ...], features: tuple[float, ...]) -> float:
    return sum(weight * feature for weight, feature in zip(weights, features, strict=True))


def _greedy_action(
    environment: SchedulingEnvironment,
    state: SchedulingState,
    actions: tuple[SchedulingAction, ...],
    weights: list[float] | tuple[float, ...],
) -> SchedulingAction:
    best = actions[0]
    best_value = _q_value(weights, environment.features(state, best))
    for action in actions[1:]:
        value = _q_value(weights, environment.features(state, action))
        if value > best_value + Q_TOLERANCE:
            best = action
            best_value = value
    return best


def _schedule_key(schedule: Schedule) -> tuple[tuple[float, str, str], ...]:
    return tuple(
        (assignment.start_s, assignment.task_id, assignment.window_id)
        for assignment in schedule.tasks
    )


def _better(
    metrics: Metrics,
    schedule: Schedule,
    incumbent_metrics: Metrics,
    incumbent_schedule: Schedule,
) -> bool:
    score = ObjectiveScore.from_metrics(metrics)
    incumbent_score = ObjectiveScore.from_metrics(incumbent_metrics)
    if score != incumbent_score:
        return score > incumbent_score
    return _schedule_key(schedule) < _schedule_key(incumbent_schedule)


def _convergence_point(evaluation: int, metrics: Metrics) -> dict[str, float | int]:
    return {
        "evaluation": evaluation,
        "total_value": metrics.total_value,
        "completed_tasks": metrics.completed_tasks,
        "total_slew_time_s": metrics.total_slew_time_s,
    }


def train_policy(
    scenario: Scenario,
    *,
    seed: int,
    config: QLearningConfig,
    started_at: float | None = None,
    time_limit_s: float | None = None,
    solver_name: str = "q-learning",
) -> TrainingOutcome:
    """Train on one scenario while retaining greedy insertion as an incumbent."""

    campaign_started_at = started_at if started_at is not None else perf_counter()
    environment = SchedulingEnvironment(scenario)
    rng = random.Random(seed)
    weights = [0.0] * len(FEATURE_NAMES)
    greedy = GreedyInsertionSolver(SolverConfig(seed=seed, time_limit_s=time_limit_s)).solve(
        scenario
    )
    incumbent_schedule = greedy.schedule
    incumbent_validation = greedy.validation
    incumbent_metrics = greedy.metrics
    convergence = [_convergence_point(0, incumbent_metrics)]
    training_trace: list[TrainingPoint] = []
    episodes_started = 0
    episodes_completed = 0
    transitions = 0
    timed_out = False
    stop_reason = "episode_budget"

    def time_limit_reached() -> bool:
        return time_limit_s is not None and perf_counter() - campaign_started_at >= time_limit_s

    for episode in range(1, config.episodes + 1):
        if time_limit_reached():
            timed_out = True
            stop_reason = "time_limit"
            break
        episodes_started += 1
        epsilon = _epsilon(config, episode)
        state = environment.reset(solver_name=solver_name, seed=seed)
        actions = environment.actions(state)
        if not actions:
            episodes_completed += 1
            metrics = environment.metrics(state)
            training_trace.append(
                TrainingPoint(
                    episode=episode,
                    epsilon=epsilon,
                    mean_abs_td_error=0.0,
                    total_value=metrics.total_value,
                    completed_tasks=metrics.completed_tasks,
                    total_slew_time_s=metrics.total_slew_time_s,
                )
            )
            stop_reason = "no_feasible_actions"
            break

        td_errors: list[float] = []
        interrupted = False
        while actions:
            if time_limit_reached():
                timed_out = True
                stop_reason = "time_limit"
                interrupted = True
                break
            action = (
                rng.choice(actions)
                if rng.random() < epsilon
                else _greedy_action(environment, state, actions, weights)
            )
            features = environment.features(state, action)
            current_q = _q_value(weights, features)
            reward = environment.reward(state, action)
            next_state = environment.transition(state, action)
            next_actions = environment.actions(next_state)
            next_q = (
                max(
                    _q_value(weights, environment.features(next_state, candidate))
                    for candidate in next_actions
                )
                if next_actions
                else 0.0
            )
            td_error = reward + config.discount_factor * next_q - current_q
            for index, feature in enumerate(features):
                weights[index] += config.learning_rate * td_error * feature
            td_errors.append(abs(td_error))
            transitions += 1
            state = next_state
            actions = next_actions

        if interrupted:
            break
        episodes_completed += 1
        metrics = environment.metrics(state)
        training_trace.append(
            TrainingPoint(
                episode=episode,
                epsilon=epsilon,
                mean_abs_td_error=fmean(td_errors) if td_errors else 0.0,
                total_value=metrics.total_value,
                completed_tasks=metrics.completed_tasks,
                total_slew_time_s=metrics.total_slew_time_s,
            )
        )
        if _better(metrics, state.schedule, incumbent_metrics, incumbent_schedule):
            incumbent_schedule = state.schedule
            incumbent_validation = state.validation
            incumbent_metrics = metrics
            convergence.append(_convergence_point(episode, metrics))

    policy = LinearQPolicy(
        training_scenario_id=scenario.scenario_id,
        scenario_sha256=scenario_fingerprint(scenario),
        feature_names=FEATURE_NAMES,
        weights=tuple(weights),
        seed=seed,
        episodes_completed=episodes_completed,
        transitions=transitions,
        learning_rate=config.learning_rate,
        discount_factor=config.discount_factor,
        initial_epsilon=config.initial_epsilon,
        final_epsilon=config.final_epsilon,
    )
    metadata: dict[str, Any] = {
        "algorithm": policy.algorithm,
        "evaluation_budget": config.episodes,
        "evaluations": episodes_completed,
        "episodes_started": episodes_started,
        "episodes_completed": episodes_completed,
        "transitions": transitions,
        "training_trace": [point.model_dump(mode="json") for point in training_trace],
        "convergence": convergence,
        "model": policy.model_dump(mode="json"),
        "timed_out": timed_out,
        "stop_reason": stop_reason,
        "incumbent_initializer": "greedy-insertion",
    }
    schedule = incumbent_schedule.model_copy(
        update={
            "solver_name": solver_name,
            "seed": seed,
            "metadata": metadata,
        }
    )
    return TrainingOutcome(
        schedule=schedule,
        validation=incumbent_validation,
        metrics=incumbent_metrics,
        policy=policy,
        training_trace=tuple(training_trace),
        convergence=tuple(convergence),
        episodes_started=episodes_started,
        episodes_completed=episodes_completed,
        transitions=transitions,
        timed_out=timed_out,
        stop_reason=stop_reason,
    )


def rollout_policy(
    scenario: Scenario,
    policy: LinearQPolicy,
    *,
    solver_name: str = "q-learning-policy",
) -> SolveResult:
    """Apply a saved policy greedily to the exact scenario it was trained on."""

    if policy.feature_names != FEATURE_NAMES:
        raise ValueError("policy feature contract is not supported by this OrbitOps version")
    if policy.training_scenario_id != scenario.scenario_id:
        raise ValueError("policy scenario_id does not match the requested scenario")
    if policy.scenario_sha256 != scenario_fingerprint(scenario):
        raise ValueError("policy scenario fingerprint does not match the requested scenario")

    started_at = perf_counter()
    environment = SchedulingEnvironment(scenario)
    state = environment.reset(solver_name=solver_name, seed=policy.seed)
    actions = environment.actions(state)
    while actions:
        action = _greedy_action(environment, state, actions, policy.weights)
        state = environment.transition(state, action)
        actions = environment.actions(state)
    schedule = state.schedule.model_copy(
        update={
            "metadata": {
                "algorithm": policy.algorithm,
                "policy_replay": True,
                "training_scenario_id": policy.training_scenario_id,
                "scenario_sha256": policy.scenario_sha256,
            }
        }
    )
    return build_solve_result(scenario, schedule, started_at=started_at)
