"""Solver contracts, baselines, and registry."""

from orbitops.solvers.base import BaseSolver, Solver, SolverConfig
from orbitops.solvers.greedy import (
    GreedyDeadlineSolver,
    GreedyDensitySolver,
    GreedyInsertionSolver,
    GreedyValueSolver,
)
from orbitops.solvers.random_feasible import RandomFeasibleSolver
from orbitops.solvers.registry import available_solvers, get_solver

__all__ = [
    "BaseSolver",
    "GreedyDeadlineSolver",
    "GreedyDensitySolver",
    "GreedyInsertionSolver",
    "GreedyValueSolver",
    "RandomFeasibleSolver",
    "Solver",
    "SolverConfig",
    "available_solvers",
    "get_solver",
]
