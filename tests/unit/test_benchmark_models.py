from pathlib import Path

import pytest
from orbitops.benchmarking import (
    BENCHMARK_RUN_CONTRACT_VERSION,
    BenchmarkReport,
    BenchmarkSpec,
    PairwiseComparison,
    SolverSummary,
    benchmark_run_key,
    generate_scenarios,
    run_benchmark,
)
from pydantic import ValidationError

from tests.factories import make_benchmark_spec

PROJECT_ROOT = Path(__file__).parents[2]


def test_full_benchmark_config_has_expected_campaign_dimensions() -> None:
    spec = BenchmarkSpec.from_toml(PROJECT_ROOT / "configs" / "benchmark-v1.toml")

    assert spec.scenario_count == 360
    assert spec.run_count == 12_600
    assert spec.evaluation_budget == 500


def test_benchmark_spec_rejects_duplicate_dimensions() -> None:
    with pytest.raises(ValidationError, match="algorithm_seeds must not contain duplicates"):
        BenchmarkSpec(
            benchmark_id="duplicate-test",
            master_seed=1,
            sizes=("tiny",),
            difficulties=("easy",),
            instances_per_cell=1,
            solvers=("genetic",),
            algorithm_seeds=(7, 7),
        )


def test_run_key_is_stable_and_covers_solver_inputs() -> None:
    spec = BenchmarkSpec.from_toml(PROJECT_ROOT / "configs" / "benchmark-smoke.toml")
    _, descriptor = generate_scenarios(spec)[0]

    first = benchmark_run_key(spec, descriptor, "genetic", 7)
    repeated = benchmark_run_key(spec, descriptor, "genetic", 7)
    changed_budget = benchmark_run_key(
        spec.model_copy(update={"evaluation_budget": spec.evaluation_budget + 1}),
        descriptor,
        "genetic",
        7,
    )

    assert first == repeated
    assert len(first) == 64
    assert changed_budget != first
    assert BENCHMARK_RUN_CONTRACT_VERSION == "2"


def test_report_reader_remains_compatible_with_pre_evidence_schema() -> None:
    report = run_benchmark(make_benchmark_spec(solvers=("greedy-insertion",), algorithm_seeds=(0,)))
    assert report.schema_version == "2"
    legacy_payload = report.model_dump(mode="json")
    legacy_payload["schema_version"] = "1"
    legacy_payload.pop("comparisons")
    for run in legacy_payload["runs"]:
        run.pop("run_contract_version")
        run.pop("run_key")
    for summary in legacy_payload["summaries"]:
        summary.pop("total_value_ci95_low")
        summary.pop("total_value_ci95_high")
        summary.pop("value_ratio_ci95_low")
        summary.pop("value_ratio_ci95_high")
        summary.pop("value_ratio_scenario_count")

    restored = BenchmarkReport.model_validate(legacy_payload)

    assert restored.comparisons == ()
    assert restored.schema_version == "1"
    assert restored.runs[0].run_contract_version is None
    assert restored.runs[0].run_key is None
    assert restored.summaries[0].total_value_ci95_low is None
    assert restored.summaries[0].value_ratio_ci95_low is None
    assert restored.summaries[0].value_ratio_scenario_count is None


def test_report_reader_accepts_legacy_pairwise_fields() -> None:
    report = run_benchmark(make_benchmark_spec(algorithm_seeds=(0,)))
    legacy_payload = report.model_dump(mode="json")
    legacy_payload["schema_version"] = "1"
    for comparison in legacy_payload["comparisons"]:
        comparison.pop("failed_both_count")
        comparison.pop("mean_normalized_value_gap")
        comparison.pop("normalized_value_gap_ci95_low")
        comparison.pop("normalized_value_gap_ci95_high")
        comparison.pop("normalized_value_gap_scenario_count")

    restored = BenchmarkReport.model_validate(legacy_payload)

    assert restored.comparisons[0].failed_both_count == 0
    assert restored.comparisons[0].mean_normalized_value_gap is None
    assert restored.comparisons[0].normalized_value_gap_scenario_count is None


def test_evidence_models_reject_partial_intervals_and_inconsistent_counts() -> None:
    report = run_benchmark(make_benchmark_spec(algorithm_seeds=(0,)))
    summary_payload = report.summaries[0].model_dump(mode="json")
    summary_payload["value_ratio_ci95_high"] = None
    with pytest.raises(ValidationError, match="value ratio confidence interval requires both"):
        SolverSummary.model_validate(summary_payload)

    comparison_payload = report.comparisons[0].model_dump(mode="json")
    comparison_payload["failed_both_count"] = 1
    with pytest.raises(ValidationError, match="non-excluded pairs"):
        PairwiseComparison.model_validate(comparison_payload)

    comparison_payload.update(
        {
            "paired_count": 1,
            "wins_a": 0,
            "ties": 0,
            "losses_a": 0,
            "failed_both_count": 1,
            "win_rate_a": 0.0,
            "both_feasible_count": 0,
            "mean_normalized_value_gap": None,
            "normalized_value_gap_ci95_low": None,
            "normalized_value_gap_ci95_high": None,
            "normalized_value_gap_scenario_count": 0,
        }
    )
    with pytest.raises(ValidationError, match="fully excluded comparisons"):
        PairwiseComparison.model_validate(comparison_payload)
