"""Common solver interface; all algorithms must implement this contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

from pydantic import Field

from orbitops.domain.models import DomainModel, Scenario, SolveResult


class SolverConfig(DomainModel):
    seed: int = 0
    time_limit_s: float | None = Field(default=None, gt=0)


@runtime_checkable
class Solver(Protocol):
    name: str

    def solve(self, scenario: Scenario) -> SolveResult:
        """Return a candidate schedule plus validation and metric artifacts."""


class BaseSolver(ABC):
    name: str

    def __init__(self, config: SolverConfig | None = None) -> None:
        self.config = config or SolverConfig()

    @abstractmethod
    def solve(self, scenario: Scenario) -> SolveResult:
        """Solve one scenario deterministically for a fixed config and seed."""
