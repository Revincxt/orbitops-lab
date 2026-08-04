"""Stable machine-readable validation codes."""

from enum import StrEnum


class ValidationCode(StrEnum):
    SCENARIO_MISMATCH = "scenario_mismatch"
    UNKNOWN_TASK = "unknown_task"
    DUPLICATE_TASK = "duplicate_task"
    UNKNOWN_WINDOW = "unknown_window"
    OUTSIDE_WINDOW = "outside_window"
    OUTSIDE_HORIZON = "outside_horizon"
    TASK_OVERLAP = "task_overlap"
    INSUFFICIENT_SLEW_TIME = "insufficient_slew_time"
    ENERGY_BELOW_ZERO = "energy_below_zero"
    STORAGE_CAPACITY_EXCEEDED = "storage_capacity_exceeded"
