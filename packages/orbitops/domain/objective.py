"""The single lexicographic objective used to compare every solver."""

from __future__ import annotations

from dataclasses import dataclass

from orbitops.domain.models import Metrics, Scenario, Schedule


@dataclass(frozen=True, order=True, slots=True)
class ObjectiveScore:
    """Larger tuple values are always better."""

    total_value: float
    completed_tasks: int
    negative_slew_time_s: float

    @classmethod
    def from_metrics(cls, metrics: Metrics) -> ObjectiveScore:
        return cls(
            total_value=metrics.total_value,
            completed_tasks=metrics.completed_tasks,
            negative_slew_time_s=-metrics.total_slew_time_s,
        )


def score_schedule(
    scenario: Scenario,
    schedule: Schedule,
    *,
    total_slew_time_s: float,
) -> Metrics:
    """Compute v0.1 metrics without making a feasibility claim."""

    task_values = {task.task_id: task.priority_value for task in scenario.tasks}
    scheduled_ids = [task.task_id for task in schedule.tasks]
    unknown_ids = sorted(set(scheduled_ids) - task_values.keys())
    if unknown_ids:
        unknown = ", ".join(unknown_ids)
        raise ValueError(f"schedule contains unknown task_id values: {unknown}")
    if len(scheduled_ids) != len(set(scheduled_ids)):
        raise ValueError("schedule cannot score the same task more than once")

    return Metrics(
        total_value=sum(task_values[task_id] for task_id in scheduled_ids),
        completed_tasks=len(scheduled_ids),
        total_slew_time_s=total_slew_time_s,
    )
