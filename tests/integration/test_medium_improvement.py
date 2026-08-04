from orbitops.domain.models import SolveResult
from orbitops.domain.objective import ObjectiveScore
from orbitops.solvers import baseline_solvers, get_solver

from tests.factories import make_seeded_scenario


def _score(result: SolveResult) -> ObjectiveScore:
    return ObjectiveScore.from_metrics(result.metrics)


def test_genetic_search_beats_best_baseline_across_five_seeds() -> None:
    scenario = make_seeded_scenario(0, task_count=14)
    baseline_results = [
        get_solver(name, seed=20260804).solve(scenario) for name in baseline_solvers()
    ]
    best_baseline = max(baseline_results, key=_score)

    for algorithm_seed in range(5):
        genetic = get_solver(
            "genetic",
            seed=algorithm_seed,
            evaluation_budget=250,
        ).solve(scenario)

        assert genetic.validation.is_feasible
        assert _score(genetic) > _score(best_baseline)
