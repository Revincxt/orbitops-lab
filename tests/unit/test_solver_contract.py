import inspect

from orbitops.solvers.base import BaseSolver, Solver, SolverConfig


def test_solver_config_has_reproducible_default_seed() -> None:
    assert SolverConfig().seed == 0


def test_solver_contract_is_runtime_checkable() -> None:
    class StructurallyValidSolver:
        name = "structural-test"

        def solve(self, scenario: object) -> object:
            raise NotImplementedError

    assert isinstance(StructurallyValidSolver(), Solver)
    assert inspect.isabstract(BaseSolver)
