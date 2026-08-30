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
    run_contract_version: str | None = Field(default=None, pattern=r"^[1-9][0-9]*$")
    run_key: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
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
    total_value_ci95_low: float | None = Field(default=None, ge=0)
    total_value_ci95_high: float | None = Field(default=None, ge=0)
    mean_completed_tasks: float | None = Field(default=None, ge=0)
    mean_total_slew_time_s: float | None = Field(default=None, ge=0)
    mean_runtime_s: float = Field(ge=0)
    mean_seed_value_stddev: float | None = Field(default=None, ge=0)
    value_ratio_ci95_low: float | None = Field(default=None, ge=0, le=1)
    value_ratio_ci95_high: float | None = Field(default=None, ge=0, le=1)
    value_ratio_scenario_count: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_confidence_interval(self) -> Self:
        legacy_bounds = (self.total_value_ci95_low, self.total_value_ci95_high)
        if (legacy_bounds[0] is None) != (legacy_bounds[1] is None):
            raise ValueError("total value confidence interval requires both bounds")
        if (
            legacy_bounds[0] is not None
            and legacy_bounds[1] is not None
            and legacy_bounds[0] > legacy_bounds[1]
        ):
            raise ValueError("total value confidence interval bounds are reversed")

        ratio_bounds = (self.value_ratio_ci95_low, self.value_ratio_ci95_high)
        if (ratio_bounds[0] is None) != (ratio_bounds[1] is None):
            raise ValueError("value ratio confidence interval requires both bounds")
        if (
            ratio_bounds[0] is not None
            and ratio_bounds[1] is not None
            and ratio_bounds[0] > ratio_bounds[1]
        ):
            raise ValueError("value ratio confidence interval bounds are reversed")
        if self.value_ratio_scenario_count == 0 and (
            self.mean_value_ratio is not None or ratio_bounds[0] is not None
        ):
            raise ValueError("zero value-ratio scenarios cannot have an estimate")
        if (
            self.value_ratio_scenario_count is not None
            and self.value_ratio_scenario_count > 0
            and (self.mean_value_ratio is None or ratio_bounds[0] is None)
        ):
            raise ValueError("value-ratio scenarios require a mean and confidence interval")
        return self


class PairwiseComparison(DomainModel):
    """Paired lexicographic outcomes for two solvers on shared scenario/seed cells."""

    solver_a: str
    solver_b: str
    paired_count: int = Field(gt=0)
    wins_a: int = Field(ge=0)
    ties: int = Field(ge=0)
    losses_a: int = Field(ge=0)
    win_rate_a: float | None = Field(default=None, ge=0, le=1)
    both_feasible_count: int = Field(ge=0)
    mean_total_value_difference: float | None = None
    value_difference_ci95_low: float | None = None
    value_difference_ci95_high: float | None = None
    failed_both_count: int = Field(default=0, ge=0)
    mean_normalized_value_gap: float | None = Field(default=None, ge=-1, le=1)
    normalized_value_gap_ci95_low: float | None = Field(default=None, ge=-1, le=1)
    normalized_value_gap_ci95_high: float | None = Field(default=None, ge=-1, le=1)
    normalized_value_gap_scenario_count: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_counts_and_interval(self) -> Self:
        analyzed_count = self.paired_count - self.failed_both_count
        if analyzed_count < 0:
            raise ValueError("failed_both_count cannot exceed paired_count")
        if self.wins_a + self.ties + self.losses_a != analyzed_count:
            raise ValueError("pairwise win/tie/loss counts must equal non-excluded pairs")
        if self.both_feasible_count > analyzed_count:
            raise ValueError("both_feasible_count cannot exceed non-excluded pairs")
        if analyzed_count == 0:
            if self.win_rate_a is not None:
                raise ValueError("fully excluded comparisons cannot have a win rate")
        else:
            expected_win_rate = self.wins_a / analyzed_count
            if self.win_rate_a is None or abs(self.win_rate_a - expected_win_rate) > 1e-12:
                raise ValueError("win_rate_a must use non-excluded pairs as its denominator")

        legacy_bounds = (self.value_difference_ci95_low, self.value_difference_ci95_high)
        if (legacy_bounds[0] is None) != (legacy_bounds[1] is None):
            raise ValueError("value difference confidence interval requires both bounds")
        if (
            legacy_bounds[0] is not None
            and legacy_bounds[1] is not None
            and legacy_bounds[0] > legacy_bounds[1]
        ):
            raise ValueError("value difference confidence interval bounds are reversed")

        gap_bounds = (
            self.normalized_value_gap_ci95_low,
            self.normalized_value_gap_ci95_high,
        )
        if (gap_bounds[0] is None) != (gap_bounds[1] is None):
            raise ValueError("normalized value gap confidence interval requires both bounds")
        if (
            gap_bounds[0] is not None
            and gap_bounds[1] is not None
            and gap_bounds[0] > gap_bounds[1]
        ):
            raise ValueError("normalized value gap confidence interval bounds are reversed")
        if self.normalized_value_gap_scenario_count == 0 and (
            self.mean_normalized_value_gap is not None or gap_bounds[0] is not None
        ):
            raise ValueError("zero normalized-gap scenarios cannot have an estimate")
        if (
            self.normalized_value_gap_scenario_count is not None
            and self.normalized_value_gap_scenario_count > 0
            and (self.mean_normalized_value_gap is None or gap_bounds[0] is None)
        ):
            raise ValueError("normalized-gap scenarios require a mean and confidence interval")
        return self


class BenchmarkEnvironment(DomainModel):
    orbitops_version: str
    python_version: str
    python_implementation: str
    platform_system: str
    platform_machine: str
    generator_version: str


class BenchmarkReport(DomainModel):
    schema_version: Literal["1", "2"] = "2"
    spec: BenchmarkSpec
    environment: BenchmarkEnvironment
    scenarios: tuple[ScenarioDescriptor, ...]
    runs: tuple[BenchmarkRunRecord, ...]
    summaries: tuple[SolverSummary, ...]
    comparisons: tuple[PairwiseComparison, ...] = ()
    reproducibility_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
