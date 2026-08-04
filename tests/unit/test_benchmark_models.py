from pathlib import Path

import pytest
from orbitops.benchmarking import BenchmarkSpec
from pydantic import ValidationError

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
