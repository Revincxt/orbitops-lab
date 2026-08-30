from __future__ import annotations

import pytest
from orbitops.benchmarking import BenchmarkRunRecord
from orbitops.benchmarking.runner import (
    normalized_value_ratios,
    pairwise_comparisons,
    summarize_runs,
)
from orbitops.domain.models import Metrics


def _run(
    solver: str,
    seed: int,
    value: float | None,
    *,
    scenario: str = "scenario",
    completed: int = 2,
    slew: float = 5.0,
) -> BenchmarkRunRecord:
    feasible = value is not None
    return BenchmarkRunRecord(
        run_id=f"{scenario}:{solver}:{seed}",
        scenario_id=scenario,
        size="tiny",
        difficulty="medium",
        instance_index=0,
        task_count=6,
        solver_name=solver,
        algorithm_seed=seed,
        evaluation_budget=20,
        feasible=feasible,
        metrics=(
            Metrics(
                total_value=value,
                completed_tasks=completed,
                total_slew_time_s=slew,
            )
            if value is not None
            else None
        ),
        runtime_s=0.1,
        error=None if feasible else "RuntimeError: failed run",
    )


def test_summary_normalizes_per_cell_and_bootstraps_the_scenario_block() -> None:
    runs = (
        _run("stable", 0, 10.0),
        _run("stable", 1, 10.0),
        _run("variable", 0, 8.0),
        _run("variable", 1, 12.0),
    )

    stable, variable = summarize_runs(runs)

    expected_ratio = (1.0 + 10.0 / 12.0) / 2
    assert stable.rank == 1
    assert stable.solver_name == "stable"
    assert stable.mean_value_ratio == expected_ratio
    assert stable.value_ratio_ci95_low == expected_ratio
    assert stable.value_ratio_ci95_high == expected_ratio
    assert stable.value_ratio_scenario_count == 1
    assert stable.total_value_ci95_low is None
    assert stable.total_value_ci95_high is None
    assert stable.mean_seed_value_stddev == 0.0
    assert variable.rank == 2
    assert variable.mean_seed_value_stddev == 2.0


def test_summary_gives_scenarios_equal_weight_when_feasible_seed_counts_differ() -> None:
    runs = (
        _run("candidate", 0, 10.0, scenario="s1"),
        _run("candidate", 1, 10.0, scenario="s1"),
        _run("reference", 0, 10.0, scenario="s1"),
        _run("reference", 1, 10.0, scenario="s1"),
        _run("candidate", 0, 0.0, scenario="s2"),
        _run("candidate", 1, None, scenario="s2"),
        _run("reference", 0, 10.0, scenario="s2"),
        _run("reference", 1, 10.0, scenario="s2"),
    )

    summaries = {summary.solver_name: summary for summary in summarize_runs(runs)}
    candidate = summaries["candidate"]

    assert candidate.feasible_rate == 0.75
    assert candidate.mean_value_ratio == 0.5
    assert candidate.value_ratio_ci95_low == 0.0
    assert candidate.value_ratio_ci95_high == 1.0
    assert candidate.value_ratio_scenario_count == 2
    assert summarize_runs(tuple(reversed(runs))) == summarize_runs(runs)


def test_pairwise_comparison_reports_normalized_scenario_block_gap() -> None:
    runs = (
        _run("alpha", 0, 12.0),
        _run("alpha", 1, 10.0),
        _run("beta", 0, 8.0),
        _run("beta", 1, 10.0),
    )

    comparison = pairwise_comparisons(runs)[0]

    assert (comparison.solver_a, comparison.solver_b) == ("alpha", "beta")
    assert comparison.paired_count == 2
    assert comparison.failed_both_count == 0
    assert (comparison.wins_a, comparison.ties, comparison.losses_a) == (1, 1, 0)
    assert comparison.win_rate_a == 0.5
    assert comparison.both_feasible_count == 2
    assert comparison.mean_total_value_difference == 2.0
    assert comparison.value_difference_ci95_low is None
    assert comparison.value_difference_ci95_high is None
    expected_gap = ((1.0 - 8.0 / 12.0) + 0.0) / 2
    assert comparison.mean_normalized_value_gap == pytest.approx(expected_gap)
    assert comparison.normalized_value_gap_ci95_low == pytest.approx(expected_gap)
    assert comparison.normalized_value_gap_ci95_high == pytest.approx(expected_gap)
    assert comparison.normalized_value_gap_scenario_count == 1


def test_pairwise_gap_gives_scenarios_equal_weight_instead_of_seed_cells() -> None:
    runs = (
        *(_run("alpha", seed, 10.0, scenario="s1") for seed in range(3)),
        *(_run("beta", seed, 8.0, scenario="s1") for seed in range(3)),
        _run("alpha", 0, 4.0, scenario="s2"),
        _run("beta", 0, 10.0, scenario="s2"),
    )

    comparison = pairwise_comparisons(runs)[0]

    assert comparison.mean_total_value_difference == 0.0
    assert comparison.mean_normalized_value_gap == pytest.approx(-0.2)
    assert comparison.normalized_value_gap_ci95_low == pytest.approx(-0.6)
    assert comparison.normalized_value_gap_ci95_high == pytest.approx(0.2)
    assert comparison.normalized_value_gap_scenario_count == 2
    assert pairwise_comparisons(tuple(reversed(runs))) == pairwise_comparisons(runs)


def test_pairwise_excludes_joint_failures_but_retains_one_sided_failures() -> None:
    runs = (
        _run("alpha", 0, None, scenario="both-fail"),
        _run("beta", 0, None, scenario="both-fail"),
        _run("alpha", 0, 5.0, scenario="alpha-only"),
        _run("beta", 0, None, scenario="alpha-only"),
        _run("alpha", 0, None, scenario="beta-only"),
        _run("beta", 0, 5.0, scenario="beta-only"),
        _run("alpha", 0, 5.0, scenario="tie"),
        _run("beta", 0, 5.0, scenario="tie"),
    )

    comparison = pairwise_comparisons(runs)[0]

    assert comparison.paired_count == 4
    assert comparison.failed_both_count == 1
    assert (comparison.wins_a, comparison.ties, comparison.losses_a) == (1, 1, 1)
    assert comparison.win_rate_a == pytest.approx(1 / 3)
    assert comparison.both_feasible_count == 1
    assert comparison.mean_normalized_value_gap == 0.0
    assert comparison.normalized_value_gap_ci95_low == 0.0
    assert comparison.normalized_value_gap_ci95_high == 0.0


def test_pairwise_all_joint_failures_have_no_rate_or_value_effect() -> None:
    runs = (
        _run("alpha", 0, None, scenario="s1"),
        _run("beta", 0, None, scenario="s1"),
        _run("alpha", 0, None, scenario="s2"),
        _run("beta", 0, None, scenario="s2"),
    )

    comparison = pairwise_comparisons(runs)[0]

    assert comparison.failed_both_count == comparison.paired_count == 2
    assert (comparison.wins_a, comparison.ties, comparison.losses_a) == (0, 0, 0)
    assert comparison.win_rate_a is None
    assert comparison.mean_normalized_value_gap is None
    assert comparison.normalized_value_gap_ci95_low is None
    assert comparison.normalized_value_gap_ci95_high is None
    assert comparison.normalized_value_gap_scenario_count == 0


def test_zero_value_normalization_and_lexicographic_value_ties_are_explicit() -> None:
    zero_runs = (_run("alpha", 0, 0.0), _run("beta", 0, 0.0))
    ratios = normalized_value_ratios(zero_runs)
    assert set(ratios.values()) == {1.0}
    assert pairwise_comparisons(zero_runs)[0].mean_normalized_value_gap == 0.0

    lexicographic_runs = (
        _run("alpha", 0, 5.0, completed=3),
        _run("beta", 0, 5.0, completed=2),
    )
    comparison = pairwise_comparisons(lexicographic_runs)[0]
    assert (comparison.wins_a, comparison.ties, comparison.losses_a) == (1, 0, 0)
    assert comparison.mean_normalized_value_gap == 0.0
