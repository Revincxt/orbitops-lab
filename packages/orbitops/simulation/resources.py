"""Resource accounting primitives for the event simulator."""

from __future__ import annotations

from dataclasses import dataclass

from orbitops.domain.models import ObservationTask, Satellite
from orbitops.domain.transitions import recharge_energy_wh


@dataclass(frozen=True, slots=True)
class TaskResourceTransition:
    energy_before_wh: float
    energy_after_wh: float
    storage_before_gb: float
    storage_after_gb: float


def execute_task_resources(
    satellite: Satellite,
    task: ObservationTask,
    *,
    current_energy_wh: float,
    current_storage_gb: float,
    idle_s: float,
) -> TaskResourceTransition:
    """Advance through idle and observation, then apply task resource costs.

    v0.1 assumes a constant background recharge rate, including during an
    observation. Observation energy is charged as a deterministic lump at the
    end of the task. Storage only increases because downlink is out of scope.
    """

    energy_before_wh = recharge_energy_wh(satellite, current_energy_wh, idle_s)
    energy_at_task_end_wh = recharge_energy_wh(
        satellite,
        energy_before_wh,
        task.duration_s,
    )
    return TaskResourceTransition(
        energy_before_wh=energy_before_wh,
        energy_after_wh=energy_at_task_end_wh - task.energy_cost_wh,
        storage_before_gb=current_storage_gb,
        storage_after_gb=current_storage_gb + task.storage_cost_gb,
    )
