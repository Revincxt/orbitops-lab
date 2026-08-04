"""Deterministic factories used by smoke benchmarks and property tests."""

from __future__ import annotations

import random

from orbitops import ObservationTask, Satellite, Scenario, Target, TimeWindow
from orbitops.benchmarking import BenchmarkSpec


def make_benchmark_spec(
    *,
    benchmark_id: str = "test-benchmark",
    sizes: tuple[str, ...] = ("tiny",),
    difficulties: tuple[str, ...] = ("medium",),
    solvers: tuple[str, ...] = ("greedy-insertion", "genetic"),
    algorithm_seeds: tuple[int, ...] = (0, 1),
    evaluation_budget: int = 30,
) -> BenchmarkSpec:
    return BenchmarkSpec.model_validate(
        {
            "benchmark_id": benchmark_id,
            "master_seed": 20260804,
            "sizes": sizes,
            "difficulties": difficulties,
            "instances_per_cell": 1,
            "solvers": solvers,
            "algorithm_seeds": algorithm_seeds,
            "evaluation_budget": evaluation_budget,
        }
    )


def make_seeded_scenario(seed: int, *, task_count: int = 8) -> Scenario:
    rng = random.Random(seed)
    horizon_end_s = 2400.0
    satellite = Satellite(
        satellite_id=f"sat-{seed:03d}",
        energy_capacity_wh=200.0,
        initial_energy_wh=rng.uniform(60.0, 160.0),
        recharge_rate_w=rng.uniform(20.0, 100.0),
        storage_capacity_gb=rng.uniform(12.0, 32.0),
        initial_storage_gb=rng.uniform(0.0, 3.0),
        initial_attitude_deg=rng.uniform(-30.0, 30.0),
        slew_rate_deg_s=rng.uniform(1.0, 5.0),
        settling_time_s=rng.uniform(0.0, 8.0),
    )
    tasks: list[ObservationTask] = []
    for index in range(task_count):
        duration_s = rng.uniform(20.0, 100.0)
        windows: list[TimeWindow] = []
        for window_index in range(rng.randint(1, 2)):
            latest_start = horizon_end_s - duration_s - 120.0
            start_s = rng.uniform(30.0, latest_start)
            end_s = min(
                horizon_end_s,
                start_s + duration_s + rng.uniform(20.0, 180.0),
            )
            windows.append(
                TimeWindow(
                    window_id=f"w-{index:02d}-{window_index}",
                    start_s=start_s,
                    end_s=end_s,
                )
            )
        tasks.append(
            ObservationTask(
                task_id=f"task-{index:02d}",
                target=Target(
                    target_id=f"target-{index:02d}",
                    name=f"Target {index:02d}",
                    latitude_deg=rng.uniform(-70.0, 70.0),
                    longitude_deg=rng.uniform(-180.0, 180.0),
                ),
                priority_value=rng.uniform(1.0, 100.0),
                duration_s=duration_s,
                visibility_windows=tuple(windows),
                required_attitude_deg=rng.uniform(-70.0, 70.0),
                energy_cost_wh=rng.uniform(4.0, 35.0),
                storage_cost_gb=rng.uniform(0.5, 5.0),
            )
        )

    return Scenario(
        scenario_id=f"seeded-{seed:03d}",
        name=f"Seeded smoke scenario {seed:03d}",
        horizon_end_s=horizon_end_s,
        satellite=satellite,
        tasks=tuple(tasks),
        metadata={"generator": "tests.factories.make_seeded_scenario", "seed": seed},
    )
