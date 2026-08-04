"""Domain contracts shared by every OrbitOps component."""

from orbitops.domain.models import (
    Metrics,
    ObservationTask,
    ResourceState,
    Satellite,
    Scenario,
    Schedule,
    ScheduledTask,
    SimulationResult,
    SolveResult,
    Target,
    TaskAssignment,
    TimeWindow,
    ValidationIssue,
    ValidationReport,
)
from orbitops.domain.objective import ObjectiveScore, score_schedule

__all__ = [
    "Metrics",
    "ObjectiveScore",
    "ObservationTask",
    "ResourceState",
    "Satellite",
    "Scenario",
    "Schedule",
    "ScheduledTask",
    "SimulationResult",
    "SolveResult",
    "Target",
    "TaskAssignment",
    "TimeWindow",
    "ValidationIssue",
    "ValidationReport",
    "score_schedule",
]
