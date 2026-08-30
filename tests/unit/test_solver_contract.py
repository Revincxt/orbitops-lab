import inspect
from time import perf_counter

import pytest
from orbitops.solvers import get_solver
from orbitops.solvers.base import BaseSolver, Solver, SolverConfig

from tests.factories import make_seeded_scenario


def test_solver_config_has_reproducible_default_seed() -> None:
    assert SolverConfig().seed == 0


def test_solver_contract_is_runtime_checkable() -> None:
    class StructurallyValidSolver:
        name = "structural-test"

        def solve(self, scenario: object) -> object:
            raise NotImplementedError

    assert isinstance(StructurallyValidSolver(), Solver)
    assert inspect.isabstract(BaseSolver)


@pytest.mark.parametrize(
    ("solver_name", "task_count"),
    (
        ("local-search", 30),
        ("genetic", 30),
        ("branch-and-bound", 16),
        ("q-learning", 30),
        ("q-policy-only", 30),
    ),
)
def test_search_deadline_covers_initialization_and_candidate_decoding(
    solver_name: str,
    task_count: int,
) -> None:
    scenario = make_seeded_scenario(91, task_count=task_count)

    started_at = perf_counter()
    result = get_solver(
        solver_name,
        seed=2,
        evaluation_budget=500,
        time_limit_s=0.000001,
    ).solve(scenario)
    elapsed_s = perf_counter() - started_at

    assert result.validation.is_feasible
    assert result.schedule.metadata["timed_out"] is True
    # The deadline is soft, but initialization must not continue as an
    # unbounded full solve after it expires.
    assert elapsed_s < 0.1
