"""Feasibility-preserving scheduling environment for reinforcement learning."""

from __future__ import annotations

from dataclasses import dataclass

from orbitops.domain.models import (
    Metrics,
    ObservationTask,
    Scenario,
    Schedule,
    ValidationReport,
)
from orbitops.domain.objective import score_schedule
from orbitops.simulation.validator import validate_schedule
from orbitops.solvers.common import InsertionCandidate, best_feasible_insertion, empty_schedule

from .models import FEATURE_NAMES


@dataclass(frozen=True, slots=True)
class SchedulingState:
    schedule: Schedule
    validation: ValidationReport
    remaining_task_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SchedulingAction:
    task: ObservationTask
    insertion: InsertionCandidate


class SchedulingEnvironment:
    """Select the next task while the shared insertion engine chooses its timing."""

    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario
        self._task_by_id = {task.task_id: task for task in scenario.tasks}
        self._task_count = max(1, len(scenario.tasks))
        self._total_value = max(1.0, sum(task.priority_value for task in scenario.tasks))
        self._max_density = max(
            (task.priority_value / task.duration_s for task in scenario.tasks),
            default=1.0,
        )
        self._max_duration = max((task.duration_s for task in scenario.tasks), default=1.0)
        self._max_energy = max((task.energy_cost_wh for task in scenario.tasks), default=1.0)
        self._max_storage = max((task.storage_cost_gb for task in scenario.tasks), default=1.0)
        self._horizon = scenario.horizon_end_s - scenario.horizon_start_s

    def reset(self, *, solver_name: str, seed: int) -> SchedulingState:
        schedule = empty_schedule(self.scenario, solver_name, seed)
        validation = validate_schedule(self.scenario, schedule)
        if not validation.is_feasible or validation.simulation is None:
            raise RuntimeError("empty learning environment failed validation")
        return SchedulingState(
            schedule=schedule,
            validation=validation,
            remaining_task_ids=tuple(sorted(self._task_by_id)),
        )

    def actions(self, state: SchedulingState) -> tuple[SchedulingAction, ...]:
        actions: list[SchedulingAction] = []
        for task_id in state.remaining_task_ids:
            task = self._task_by_id[task_id]
            insertion = best_feasible_insertion(self.scenario, state.schedule, task)
            if insertion is not None:
                actions.append(SchedulingAction(task=task, insertion=insertion))
        return tuple(actions)

    @staticmethod
    def _scheduled_ids(schedule: Schedule) -> frozenset[str]:
        return frozenset(assignment.task_id for assignment in schedule.tasks)

    def _validate_action(self, state: SchedulingState, action: SchedulingAction) -> None:
        if action.task.task_id not in state.remaining_task_ids:
            raise ValueError("learning action does not reference a remaining task")
        before = self._scheduled_ids(state.schedule)
        after = self._scheduled_ids(action.insertion.schedule)
        if after != before | {action.task.task_id}:
            raise ValueError("learning action must add exactly its selected task")

    def transition(self, state: SchedulingState, action: SchedulingAction) -> SchedulingState:
        self._validate_action(state, action)
        remaining = tuple(
            task_id for task_id in state.remaining_task_ids if task_id != action.task.task_id
        )
        return SchedulingState(
            schedule=action.insertion.schedule,
            validation=action.insertion.validation,
            remaining_task_ids=remaining,
        )

    @staticmethod
    def _simulation_slew(state: SchedulingState) -> float:
        simulation = state.validation.simulation
        if simulation is None:
            raise RuntimeError("learning state is missing a simulation result")
        return simulation.total_slew_time_s

    def metrics(self, state: SchedulingState) -> Metrics:
        return score_schedule(
            self.scenario,
            state.schedule,
            total_slew_time_s=self._simulation_slew(state),
        )

    @staticmethod
    def _clamp(value: float) -> float:
        return min(1.0, max(0.0, value))

    def features(
        self,
        state: SchedulingState,
        action: SchedulingAction,
    ) -> tuple[float, ...]:
        self._validate_action(state, action)
        task = action.task
        next_simulation = action.insertion.validation.simulation
        if next_simulation is None:
            raise RuntimeError("learning action is missing a simulation result")
        inserted = action.insertion.inserted
        window = next(
            candidate
            for candidate in task.visibility_windows
            if candidate.window_id == inserted.window_id
        )
        slack_s = window.end_s - (inserted.start_s + task.duration_s)
        incremental_slew = max(
            0.0,
            next_simulation.total_slew_time_s - self._simulation_slew(state),
        )
        satellite = self.scenario.satellite
        features = (
            1.0,
            task.priority_value / self._total_value,
            (task.priority_value / task.duration_s) / max(self._max_density, 1e-12),
            1.0 - self._clamp(slack_s / self._horizon),
            1.0 - self._clamp(task.duration_s / self._max_duration),
            1.0 - self._clamp(task.energy_cost_wh / max(self._max_energy, 1e-12)),
            1.0 - self._clamp(task.storage_cost_gb / max(self._max_storage, 1e-12)),
            1.0 - self._clamp(incremental_slew / self._horizon),
            len(state.remaining_task_ids) / self._task_count,
            self._clamp(next_simulation.final_state.energy_wh / satellite.energy_capacity_wh),
            1.0
            - self._clamp(next_simulation.final_state.storage_gb / satellite.storage_capacity_gb),
        )
        assert len(features) == len(FEATURE_NAMES)
        return features

    def reward(self, state: SchedulingState, action: SchedulingAction) -> float:
        self._validate_action(state, action)
        next_simulation = action.insertion.validation.simulation
        if next_simulation is None:
            raise RuntimeError("learning action is missing a simulation result")
        incremental_slew = max(
            0.0,
            next_simulation.total_slew_time_s - self._simulation_slew(state),
        )
        value_reward = action.task.priority_value / self._total_value
        completion_bonus = 0.01 / self._task_count
        slew_penalty = 0.001 * incremental_slew / self._horizon
        return value_reward + completion_bonus - slew_penalty
