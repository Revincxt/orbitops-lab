"""Descriptive metrics derived from the shared simulator, not a new objective."""

from __future__ import annotations

from typing import Any

from orbitops.domain.models import Scenario, SolveResult


def evaluation_metrics(scenario: Scenario, result: SolveResult) -> dict[str, Any]:
    """Use EOS-compatible TP/TCR/TM; single-satellite BD is not informative."""
    horizon = scenario.horizon_end_s - scenario.horizon_start_s
    tasks = {task.task_id: task for task in scenario.tasks}
    simulation = result.validation.simulation
    assigned = {task.task_id: task for task in simulation.tasks} if simulation else {}
    assigned = {key: value for key, value in assigned.items() if key in tasks}
    count = len(tasks)
    delay = sum(max(0, task.start_s - scenario.horizon_start_s) for task in assigned.values())
    tm = (delay + (count - len(assigned)) * horizon) / (count * horizon) if count else 0.0
    return {
        "TP": sum(tasks[key].priority_value for key in assigned),
        "TCR": len(assigned) / count if count else 0.0,
        "TM": tm,
        "BD": None,
        "RT": result.runtime_s,
        "observation_utilization": sum(task.end_s - task.start_s for task in assigned.values())
        / horizon,
        "basis": "shared simulator; descriptive metrics do not certify feasibility",
        "objective": "lexicographic: TP, task count, then minimum slew time",
    }
