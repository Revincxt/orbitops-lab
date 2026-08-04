"""Solver contracts, baselines, and registry."""

from orbitops.solvers.base import BaseSolver, Solver, SolverConfig
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
from orbitops.solvers.random_feasible import RandomFeasibleSolver
from orbitops.solvers.registry import (
    advanced_solvers,
    available_solvers,
    baseline_solvers,
    exact_solvers,
    get_solver,
)

__all__ = [
    "BaseSolver",
    "BranchAndBoundSolver",
    "BruteForceSolver",
    "GeneticSolver",
    "GreedyDeadlineSolver",
    "GreedyDensitySolver",
    "GreedyInsertionSolver",
    "GreedyValueSolver",
    "LocalSearchSolver",
    "RandomFeasibleSolver",
    "Solver",
    "SolverConfig",
    "advanced_solvers",
    "available_solvers",
    "baseline_solvers",
    "exact_solvers",
    "get_solver",
]
