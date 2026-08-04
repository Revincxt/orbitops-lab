"""Deterministic benchmark scenario generation."""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass

from orbitops.benchmarking.models import (
    BenchmarkSpec,
    ScenarioDescriptor,
    ScenarioDifficulty,
    ScenarioSize,
)
from orbitops.domain.models import ObservationTask, Satellite, Scenario, Target, TimeWindow

GENERATOR_VERSION = "benchmark-generator-v1"
TASK_COUNTS: dict[ScenarioSize, int] = {
    "tiny": 6,
    "small": 10,
    "medium": 18,
    "large": 30,
}


@dataclass(frozen=True, slots=True)
class DifficultyProfile:
    window_count: tuple[int, int]
    window_slack_s: tuple[float, float]
    initial_energy_fraction: tuple[float, float]
    recharge_rate_w: tuple[float, float]
    initial_storage_fraction: tuple[float, float]
    slew_rate_deg_s: tuple[float, float]
    settling_time_s: tuple[float, float]
    attitude_limit_deg: float
    energy_cost_wh: tuple[float, float]
    storage_cost_gb: tuple[float, float]
    clustered_windows: bool


DIFFICULTY_PROFILES: dict[ScenarioDifficulty, DifficultyProfile] = {
    "easy": DifficultyProfile(
        window_count=(2, 3),
        window_slack_s=(140.0, 320.0),
        initial_energy_fraction=(0.8, 1.0),
        recharge_rate_w=(70.0, 120.0),
        initial_storage_fraction=(0.0, 0.05),
        slew_rate_deg_s=(4.0, 7.0),
        settling_time_s=(0.0, 3.0),
        attitude_limit_deg=35.0,
        energy_cost_wh=(3.0, 12.0),
        storage_cost_gb=(0.3, 1.5),
        clustered_windows=False,
    ),
    "medium": DifficultyProfile(
        window_count=(1, 2),
        window_slack_s=(60.0, 180.0),
        initial_energy_fraction=(0.55, 0.8),
        recharge_rate_w=(30.0, 80.0),
        initial_storage_fraction=(0.03, 0.12),
        slew_rate_deg_s=(2.0, 4.5),
        settling_time_s=(2.0, 7.0),
        attitude_limit_deg=60.0,
        energy_cost_wh=(7.0, 24.0),
        storage_cost_gb=(0.8, 3.0),
        clustered_windows=False,
    ),
    "hard": DifficultyProfile(
        window_count=(1, 1),
        window_slack_s=(15.0, 70.0),
        initial_energy_fraction=(0.35, 0.6),
        recharge_rate_w=(10.0, 45.0),
        initial_storage_fraction=(0.08, 0.2),
        slew_rate_deg_s=(1.0, 2.5),
        settling_time_s=(5.0, 12.0),
        attitude_limit_deg=80.0,
        energy_cost_wh=(12.0, 32.0),
        storage_cost_gb=(1.5, 4.5),
        clustered_windows=True,
    ),
}


def _stable_seed(
    spec: BenchmarkSpec,
    size: ScenarioSize,
    difficulty: ScenarioDifficulty,
    index: int,
) -> int:
    identity = "|".join(
        (
            GENERATOR_VERSION,
            spec.benchmark_id,
            str(spec.master_seed),
            size,
            difficulty,
            str(index),
        )
    )
    digest = hashlib.sha256(identity.encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _canonical_sha256(scenario: Scenario) -> str:
    payload = json.dumps(
        scenario.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _window_start(
    rng: random.Random,
    *,
    horizon_end_s: float,
    duration_s: float,
    slack_s: float,
    clustered: bool,
) -> float:
    latest = horizon_end_s - duration_s - slack_s
    if not clustered:
        return rng.uniform(20.0, latest)
    center = horizon_end_s * 0.5
    clustered_start = rng.gauss(center, horizon_end_s * 0.11)
    return min(max(20.0, clustered_start), latest)


def generate_scenario(
    spec: BenchmarkSpec,
    size: ScenarioSize,
    difficulty: ScenarioDifficulty,
    instance_index: int,
) -> tuple[Scenario, ScenarioDescriptor]:
    """Generate one immutable scenario and its integrity descriptor."""

    seed = _stable_seed(spec, size, difficulty, instance_index)
    rng = random.Random(seed)
    profile = DIFFICULTY_PROFILES[difficulty]
    task_count = TASK_COUNTS[size]
    horizon_end_s = 2400.0
    energy_capacity_wh = 220.0
    storage_capacity_gb = 42.0
    satellite = Satellite(
        satellite_id=f"sat-{size}-{difficulty}-{instance_index:03d}",
        energy_capacity_wh=energy_capacity_wh,
        initial_energy_wh=energy_capacity_wh * rng.uniform(*profile.initial_energy_fraction),
        recharge_rate_w=rng.uniform(*profile.recharge_rate_w),
        storage_capacity_gb=storage_capacity_gb,
        initial_storage_gb=storage_capacity_gb * rng.uniform(*profile.initial_storage_fraction),
        initial_attitude_deg=rng.uniform(-20.0, 20.0),
        slew_rate_deg_s=rng.uniform(*profile.slew_rate_deg_s),
        settling_time_s=rng.uniform(*profile.settling_time_s),
    )
    tasks: list[ObservationTask] = []
    for task_index in range(task_count):
        duration_s = rng.uniform(30.0, 105.0)
        windows: list[TimeWindow] = []
        window_count = rng.randint(*profile.window_count)
        for window_index in range(window_count):
            slack_s = rng.uniform(*profile.window_slack_s)
            start_s = _window_start(
                rng,
                horizon_end_s=horizon_end_s,
                duration_s=duration_s,
                slack_s=slack_s,
                clustered=profile.clustered_windows,
            )
            windows.append(
                TimeWindow(
                    window_id=f"w-{task_index:03d}-{window_index}",
                    start_s=start_s,
                    end_s=start_s + duration_s + slack_s,
                )
            )
        tasks.append(
            ObservationTask(
                task_id=f"task-{task_index:03d}",
                target=Target(
                    target_id=f"target-{task_index:03d}",
                    name=f"Target {task_index:03d}",
                    latitude_deg=rng.uniform(-70.0, 70.0),
                    longitude_deg=rng.uniform(-180.0, 180.0),
                ),
                priority_value=rng.uniform(1.0, 100.0),
                duration_s=duration_s,
                visibility_windows=tuple(windows),
                required_attitude_deg=rng.uniform(
                    -profile.attitude_limit_deg,
                    profile.attitude_limit_deg,
                ),
                energy_cost_wh=rng.uniform(*profile.energy_cost_wh),
                storage_cost_gb=rng.uniform(*profile.storage_cost_gb),
            )
        )

    scenario_id = f"{spec.benchmark_id}-{size}-{difficulty}-{instance_index:03d}"
    scenario = Scenario(
        scenario_id=scenario_id,
        name=f"{size.title()} {difficulty} benchmark instance {instance_index:03d}",
        horizon_end_s=horizon_end_s,
        satellite=satellite,
        tasks=tuple(tasks),
        metadata={
            "benchmark_id": spec.benchmark_id,
            "generator": GENERATOR_VERSION,
            "generator_seed": seed,
            "size": size,
            "difficulty": difficulty,
            "instance_index": instance_index,
        },
    )
    descriptor = ScenarioDescriptor(
        scenario_id=scenario.scenario_id,
        size=size,
        difficulty=difficulty,
        instance_index=instance_index,
        task_count=task_count,
        generator_seed=seed,
        sha256=_canonical_sha256(scenario),
    )
    return scenario, descriptor


def generate_scenarios(
    spec: BenchmarkSpec,
) -> tuple[tuple[Scenario, ScenarioDescriptor], ...]:
    return tuple(
        generate_scenario(spec, size, difficulty, instance_index)
        for size in spec.sizes
        for difficulty in spec.difficulties
        for instance_index in range(spec.instances_per_cell)
    )
