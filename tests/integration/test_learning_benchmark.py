from pathlib import Path

from orbitops.benchmarking import BenchmarkSpec, run_benchmark

PROJECT_ROOT = Path(__file__).parents[2]
CONFIG_PATH = PROJECT_ROOT / "configs" / "learning-smoke.toml"


def test_learning_smoke_campaign_is_feasible_and_reproducible() -> None:
    spec = BenchmarkSpec.from_toml(CONFIG_PATH)

    first = run_benchmark(spec)
    second = run_benchmark(spec)

    assert first.reproducibility_fingerprint == second.reproducibility_fingerprint
    assert len(first.runs) == 8
    assert all(run.feasible for run in first.runs)
    q_runs = [run for run in first.runs if run.solver_name == "q-learning"]
    assert len(q_runs) == 4
    assert all(run.evaluations == 40 for run in q_runs)
    assert all(run.stop_reason == "episode_budget" for run in q_runs)
