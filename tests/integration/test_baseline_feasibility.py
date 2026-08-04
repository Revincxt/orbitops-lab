from orbitops.solvers import baseline_solvers, get_solver

from tests.factories import make_seeded_scenario


def test_all_baselines_are_feasible_on_100_fixed_scenarios() -> None:
    for seed in range(100):
        scenario = make_seeded_scenario(seed)
        for solver_name in baseline_solvers():
            result = get_solver(solver_name, seed=20260804).solve(scenario)

            assert result.validation.is_feasible, (seed, solver_name, result.validation.issues)
            assert result.validation.simulation is not None
            assert result.schedule.scenario_id == scenario.scenario_id
            assert result.metrics.completed_tasks == len(result.schedule.tasks)
