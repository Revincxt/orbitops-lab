"""Stable names and construction for built-in solvers."""

from __future__ import annotations

from collections.abc import Callable

from orbitops.solvers.base import BaseSolver, SolverConfig
from orbitops.solvers.branch_and_bound import BranchAndBoundSolver
from orbitops.solvers.brute_force import BruteForceSolver
from orbitops.solvers.genetic import GeneticSolver
from orbitops.solvers.greedy import (
    GreedyDeadlineSolver,
    GreedyDensitySolver,
    GreedyInsertionSolver,
    GreedyValueSolver,
)
from orbitops.solvers.local_search import LocalSearchSolver
from orbitops.solvers.q_learning import QLearningSolver
from orbitops.solvers.random_feasible import RandomFeasibleSolver

SolverFactory = Callable[[SolverConfig | None], BaseSolver]

_SOLVERS: dict[str, SolverFactory] = {
    BranchAndBoundSolver.name: BranchAndBoundSolver,
    BruteForceSolver.name: BruteForceSolver,
    GeneticSolver.name: GeneticSolver,
    RandomFeasibleSolver.name: RandomFeasibleSolver,
    GreedyValueSolver.name: GreedyValueSolver,
    GreedyDensitySolver.name: GreedyDensitySolver,
    GreedyDeadlineSolver.name: GreedyDeadlineSolver,
    GreedyInsertionSolver.name: GreedyInsertionSolver,
    LocalSearchSolver.name: LocalSearchSolver,
    QLearningSolver.name: QLearningSolver,
}

_BASELINE_SOLVERS = (
    GreedyDeadlineSolver.name,
    GreedyDensitySolver.name,
    GreedyInsertionSolver.name,
    GreedyValueSolver.name,
    RandomFeasibleSolver.name,
)

_EXACT_SOLVERS = (
    BranchAndBoundSolver.name,
    BruteForceSolver.name,
)

_ADVANCED_SOLVERS = (
    GeneticSolver.name,
    LocalSearchSolver.name,
    QLearningSolver.name,
)


def available_solvers() -> tuple[str, ...]:
    return tuple(sorted(_SOLVERS))


def baseline_solvers() -> tuple[str, ...]:
    return _BASELINE_SOLVERS


def exact_solvers() -> tuple[str, ...]:
    return _EXACT_SOLVERS


def advanced_solvers() -> tuple[str, ...]:
    return _ADVANCED_SOLVERS


def get_solver(
    name: str,
    *,
    seed: int = 0,
    time_limit_s: float | None = None,
    evaluation_budget: int = 500,
) -> BaseSolver:
    try:
        factory = _SOLVERS[name]
    except KeyError as exc:
        choices = ", ".join(available_solvers())
        raise ValueError(f"unknown solver {name!r}; choose one of: {choices}") from exc
    return factory(
        SolverConfig(
            seed=seed,
            time_limit_s=time_limit_s,
            evaluation_budget=evaluation_budget,
        )
    )
