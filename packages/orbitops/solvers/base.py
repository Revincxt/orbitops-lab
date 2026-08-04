"""Common solver interface; all algorithms must implement this contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from time import perf_counter
from typing import Protocol, runtime_checkable

from pydantic import Field

from orbitops.domain.models import DomainModel, Scenario, SolveResult


class SolverConfig(DomainModel):
    seed: int = 0
    time_limit_s: float | None = Field(default=None, gt=0)
    evaluation_budget: int = Field(default=500, gt=0)


@runtime_checkable
class Solver(Protocol):
    name: str

    def solve(self, scenario: Scenario) -> SolveResult:
        """Return a candidate schedule plus validation and metric artifacts."""


class BaseSolver(ABC):
    name: str

    def __init__(self, config: SolverConfig | None = None) -> None:
        self.config = config or SolverConfig()

    def _time_limit_reached(self, started_at: float) -> bool:
        if self.config.time_limit_s is None:
            return False
        return perf_counter() - started_at >= self.config.time_limit_s

    @abstractmethod
    def solve(self, scenario: Scenario) -> SolveResult:
        """Solve one scenario deterministically for a fixed config and seed."""
