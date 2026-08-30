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

    def __init__(
        self,
        config: SolverConfig | None = None,
        *,
        deadline_at: float | None = None,
    ) -> None:
        self.config = config or SolverConfig()
        self._inherited_deadline_at = deadline_at

    def _deadline_at(self, started_at: float) -> float | None:
        own_deadline = (
            started_at + self.config.time_limit_s if self.config.time_limit_s is not None else None
        )
        if own_deadline is None:
            return self._inherited_deadline_at
        if self._inherited_deadline_at is None:
            return own_deadline
        return min(own_deadline, self._inherited_deadline_at)

    def _time_limit_reached(self, started_at: float) -> bool:
        deadline_at = self._deadline_at(started_at)
        return deadline_at is not None and perf_counter() >= deadline_at

    @abstractmethod
    def solve(self, scenario: Scenario) -> SolveResult:
        """Solve one scenario deterministically for a fixed config and seed."""
