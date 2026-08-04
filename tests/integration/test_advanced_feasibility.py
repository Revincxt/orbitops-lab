from orbitops.solvers import advanced_solvers, get_solver

from tests.factories import make_seeded_scenario


def test_advanced_solvers_are_feasible_on_50_fixed_scenarios() -> None:
    for scenario_seed in range(50):
        scenario = make_seeded_scenario(scenario_seed)
        for solver_name in advanced_solvers():
            result = get_solver(
                solver_name,
                seed=20260804,
                evaluation_budget=60,
            ).solve(scenario)

            assert result.validation.is_feasible, (
                scenario_seed,
                solver_name,
                result.validation.issues,
            )
            assert result.schedule.metadata["evaluations"] <= 60
