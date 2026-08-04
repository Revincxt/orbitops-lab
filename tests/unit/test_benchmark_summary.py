from orbitops.benchmarking import BenchmarkRunRecord
from orbitops.benchmarking.runner import summarize_runs
from orbitops.domain.models import Metrics


def _run(solver: str, seed: int, value: float) -> BenchmarkRunRecord:
    return BenchmarkRunRecord(
        run_id=f"scenario:{solver}:{seed}",
        scenario_id="scenario",
        size="tiny",
        difficulty="medium",
        instance_index=0,
        task_count=6,
        solver_name=solver,
        algorithm_seed=seed,
        evaluation_budget=20,
        feasible=True,
        metrics=Metrics(
            total_value=value,
            completed_tasks=2,
            total_slew_time_s=5.0,
        ),
        runtime_s=0.1,
    )


def test_summary_normalizes_per_scenario_seed_and_reports_stability() -> None:
    runs = (
        _run("stable", 0, 10.0),
        _run("stable", 1, 10.0),
        _run("variable", 0, 8.0),
        _run("variable", 1, 12.0),
    )

    stable, variable = summarize_runs(runs)

    assert stable.rank == 1
    assert stable.solver_name == "stable"
    assert stable.mean_value_ratio == (1.0 + 10.0 / 12.0) / 2
    assert stable.mean_seed_value_stddev == 0.0
    assert variable.rank == 2
    assert variable.mean_seed_value_stddev == 2.0
