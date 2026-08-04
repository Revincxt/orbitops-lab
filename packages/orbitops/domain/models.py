"""Versioned, immutable data contracts for OrbitOps Lab v0.1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DomainModel(BaseModel):
    """Strict immutable base model used at every package boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class TimeWindow(DomainModel):
    """Half-open interval `[start_s, end_s)` in scenario-relative seconds."""

    window_id: str = Field(min_length=1)
    start_s: float = Field(ge=0)
    end_s: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        if self.end_s <= self.start_s:
            raise ValueError("time window end_s must be greater than start_s")
        return self

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


class Target(DomainModel):
    target_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    latitude_deg: float = Field(ge=-90, le=90)
    longitude_deg: float = Field(ge=-180, le=180)


class Satellite(DomainModel):
    satellite_id: str = Field(min_length=1)
    energy_capacity_wh: float = Field(gt=0)
    initial_energy_wh: float = Field(ge=0)
    recharge_rate_w: float = Field(ge=0)
    storage_capacity_gb: float = Field(gt=0)
    initial_storage_gb: float = Field(ge=0)
    initial_attitude_deg: float = Field(ge=-180, le=180)
    slew_rate_deg_s: float = Field(gt=0)
    settling_time_s: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_initial_resources(self) -> Self:
        if self.initial_energy_wh > self.energy_capacity_wh:
            raise ValueError("initial energy cannot exceed energy capacity")
        if self.initial_storage_gb > self.storage_capacity_gb:
            raise ValueError("initial storage cannot exceed storage capacity")
        return self


class ObservationTask(DomainModel):
    task_id: str = Field(min_length=1)
    target: Target
    priority_value: float = Field(ge=0)
    duration_s: float = Field(gt=0)
    visibility_windows: tuple[TimeWindow, ...] = Field(min_length=1)
    required_attitude_deg: float = Field(ge=-180, le=180)
    energy_cost_wh: float = Field(ge=0)
    storage_cost_gb: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_windows(self) -> Self:
        window_ids = [window.window_id for window in self.visibility_windows]
        if len(window_ids) != len(set(window_ids)):
            raise ValueError("window_id values must be unique within a task")
        if not any(window.duration_s >= self.duration_s for window in self.visibility_windows):
            raise ValueError("task duration must fit in at least one visibility window")
        return self


class Scenario(DomainModel):
    schema_version: Literal["0.1"] = "0.1"
    scenario_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    horizon_start_s: float = Field(default=0, ge=0)
    horizon_end_s: float = Field(gt=0)
    satellite: Satellite
    tasks: tuple[ObservationTask, ...]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_scenario(self) -> Self:
        if self.horizon_end_s <= self.horizon_start_s:
            raise ValueError("horizon_end_s must be greater than horizon_start_s")

        task_ids = [task.task_id for task in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("task_id values must be unique within a scenario")

        for task in self.tasks:
            for window in task.visibility_windows:
                if window.start_s < self.horizon_start_s or window.end_s > self.horizon_end_s:
                    raise ValueError(
                        f"window {window.window_id!r} for task {task.task_id!r} "
                        "must lie inside the scenario horizon"
                    )
        return self

    @classmethod
    def from_json(cls, path: str | Path) -> Self:
        """Load and validate a UTF-8 JSON scenario from disk."""

        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))

    def to_json(self, path: str | Path) -> None:
        """Write a canonical, human-readable scenario file."""

        payload = self.model_dump(mode="json")
        Path(path).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


class ScheduledTask(DomainModel):
    task_id: str = Field(min_length=1)
    start_s: float = Field(ge=0)
    end_s: float = Field(gt=0)
    window_id: str = Field(min_length=1)
    energy_before_wh: float = Field(ge=0)
    energy_after_wh: float = Field(ge=0)
    storage_before_gb: float = Field(ge=0)
    storage_after_gb: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        if self.end_s <= self.start_s:
            raise ValueError("scheduled task end_s must be greater than start_s")
        return self


class Schedule(DomainModel):
    scenario_id: str = Field(min_length=1)
    solver_name: str = Field(min_length=1)
    tasks: tuple[ScheduledTask, ...] = ()
    seed: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ValidationIssue(DomainModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    severity: Literal["error", "warning"] = "error"
    task_id: str | None = None


class ValidationReport(DomainModel):
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def is_feasible(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)


class Metrics(DomainModel):
    total_value: float = Field(ge=0)
    completed_tasks: int = Field(ge=0)
    total_slew_time_s: float = Field(ge=0)


class SolveResult(DomainModel):
    schedule: Schedule
    validation: ValidationReport
    metrics: Metrics
    runtime_s: float = Field(ge=0)
