"""Typed contracts for reproducible OrbitOps benchmark campaigns."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from orbitops.domain.models import DomainModel, Metrics

ScenarioSize = Literal["tiny", "small", "medium", "large"]
ScenarioDifficulty = Literal["easy", "medium", "hard"]


class BenchmarkSpec(DomainModel):
    """Complete input contract for one benchmark campaign."""

    schema_version: Literal["1"] = "1"
    benchmark_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    scenario_schema_version: Literal["0.1"] = "0.1"
    master_seed: int
    sizes: tuple[ScenarioSize, ...] = Field(min_length=1)
    difficulties: tuple[ScenarioDifficulty, ...] = Field(min_length=1)
    instances_per_cell: int = Field(gt=0)
    solvers: tuple[str, ...] = Field(min_length=1)
    algorithm_seeds: tuple[int, ...] = Field(min_length=1)
    evaluation_budget: int = Field(default=500, gt=0)
    time_limit_s: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_unique_dimensions(self) -> Self:
        dimensions = {
            "sizes": self.sizes,
            "difficulties": self.difficulties,
            "solvers": self.solvers,
            "algorithm_seeds": self.algorithm_seeds,
        }
        for name, values in dimensions.items():
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must not contain duplicates")
        return self

    @property
    def scenario_count(self) -> int:
        return len(self.sizes) * len(self.difficulties) * self.instances_per_cell

    @property
    def run_count(self) -> int:
        return self.scenario_count * len(self.solvers) * len(self.algorithm_seeds)

    @classmethod
    def from_toml(cls, path: str | Path) -> Self:
        payload = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(payload)


class ScenarioDescriptor(DomainModel):
    scenario_id: str
    size: ScenarioSize
    difficulty: ScenarioDifficulty
    instance_index: int = Field(ge=0)
    task_count: int = Field(ge=0)
    generator_seed: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ConvergencePoint(DomainModel):
    evaluation: int = Field(ge=0)
    total_value: float = Field(ge=0)
    completed_tasks: int = Field(ge=0)
    total_slew_time_s: float = Field(ge=0)


class BenchmarkRunRecord(DomainModel):
    run_id: str
    scenario_id: str
    size: ScenarioSize
    difficulty: ScenarioDifficulty
    instance_index: int = Field(ge=0)
    task_count: int = Field(ge=0)
    solver_name: str
    algorithm_seed: int
    evaluation_budget: int = Field(gt=0)
    feasible: bool
    metrics: Metrics | None = None
    runtime_s: float = Field(ge=0)
    evaluations: int | None = Field(default=None, ge=0)
    stop_reason: str | None = None
    convergence: tuple[ConvergencePoint, ...] = ()
    error: str | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.feasible and self.metrics is None:
            raise ValueError("feasible benchmark runs require metrics")
        if self.error is not None and self.feasible:
            raise ValueError("failed benchmark runs cannot be marked feasible")
        return self


class SolverSummary(DomainModel):
    rank: int = Field(gt=0)
    solver_name: str
    run_count: int = Field(gt=0)
    feasible_count: int = Field(ge=0)
    feasible_rate: float = Field(ge=0, le=1)
    mean_value_ratio: float | None = Field(default=None, ge=0, le=1)
    best_observed_rate: float | None = Field(default=None, ge=0, le=1)
    mean_total_value: float | None = Field(default=None, ge=0)
    median_total_value: float | None = Field(default=None, ge=0)
    mean_completed_tasks: float | None = Field(default=None, ge=0)
    mean_total_slew_time_s: float | None = Field(default=None, ge=0)
    mean_runtime_s: float = Field(ge=0)
    mean_seed_value_stddev: float | None = Field(default=None, ge=0)


class BenchmarkEnvironment(DomainModel):
    orbitops_version: str
    python_version: str
    python_implementation: str
    platform_system: str
    platform_machine: str
    generator_version: str


class BenchmarkReport(DomainModel):
    schema_version: Literal["1"] = "1"
    spec: BenchmarkSpec
    environment: BenchmarkEnvironment
    scenarios: tuple[ScenarioDescriptor, ...]
    runs: tuple[BenchmarkRunRecord, ...]
    summaries: tuple[SolverSummary, ...]
    reproducibility_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
