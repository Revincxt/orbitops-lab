"""Regenerate the committed v0.2 research-interface showcase scenarios."""

from __future__ import annotations

from pathlib import Path

from orbitops.benchmarking.generator import generate_scenario
from orbitops.benchmarking.models import BenchmarkSpec, ScenarioDifficulty, ScenarioSize
from orbitops.domain.models import Scenario, Target, TimeWindow

PROJECT_ROOT = Path(__file__).parents[1]
OUTPUT_DIR = PROJECT_ROOT / "scenarios" / "showcase"
SHOWCASE_DECIMAL_PLACES = 6

# Ordered to keep every prefix geographically diverse. Coordinates are WGS84
# reference points for display; access windows remain explicitly synthetic.
REFERENCE_TARGETS = (
    ("Shanghai", 31.2304, 121.4737),
    ("Paris", 48.8566, 2.3522),
    ("São Paulo", -23.5505, -46.6333),
    ("Sydney", -33.8688, 151.2093),
    ("Nairobi", -1.2921, 36.8219),
    ("San Francisco", 37.7749, -122.4194),
    ("Mumbai", 19.0760, 72.8777),
    ("Reykjavík", 64.1466, -21.9426),
    ("Tokyo", 35.6762, 139.6503),
    ("Cape Town", -33.9249, 18.4241),
    ("Mexico City", 19.4326, -99.1332),
    ("Dubai", 25.2048, 55.2708),
    ("London", 51.5074, -0.1278),
    ("Santiago", -33.4489, -70.6693),
    ("Bangkok", 13.7563, 100.5018),
    ("Vancouver", 49.2827, -123.1207),
    ("Cairo", 30.0444, 31.2357),
    ("Singapore", 1.3521, 103.8198),
    ("New York", 40.7128, -74.0060),
    ("Buenos Aires", -34.6037, -58.3816),
    ("Seoul", 37.5665, 126.9780),
    ("Lagos", 6.5244, 3.3792),
    ("Rome", 41.9028, 12.4964),
    ("Toronto", 43.6532, -79.3832),
    ("Jakarta", -6.2088, 106.8456),
    ("Madrid", 40.4168, -3.7038),
    ("Lima", -12.0464, -77.0428),
    ("Istanbul", 41.0082, 28.9784),
    ("Honolulu", 21.3099, -157.8581),
    ("Wuhan", 30.5928, 114.3055),
)

SHOWCASES: tuple[
    tuple[str, str, ScenarioSize, ScenarioDifficulty, str],
    ...,
] = (
    (
        "temporal-conflicts-06.json",
        "showcase-temporal-06",
        "tiny",
        "medium",
        "How do methods resolve overlapping access windows?",
    ),
    (
        "resource-frontier-10.json",
        "showcase-resources-10",
        "small",
        "hard",
        "Which observations survive simultaneous energy and storage pressure?",
    ),
    (
        "slew-corridor-18.json",
        "showcase-slew-18",
        "medium",
        "hard",
        "How do methods sequence angularly dispersed targets under a "
        "lexicographic value-first objective?",
    ),
    (
        "global-density-30.json",
        "showcase-global-30",
        "large",
        "hard",
        "How do scalable heuristics behave on a dense global target set?",
    ),
)


def _quantize(value: float) -> float:
    """Remove platform-level libm noise from committed synthetic fixtures."""

    return round(value, SHOWCASE_DECIMAL_PLACES)


def build_showcase(
    scenario_id: str,
    size: ScenarioSize,
    difficulty: ScenarioDifficulty,
    research_question: str,
) -> Scenario:
    """Create one deterministic, geographically interpretable showcase."""

    spec = BenchmarkSpec(
        benchmark_id="orbitops-showcase-v02",
        master_seed=20260830,
        sizes=(size,),
        difficulties=(difficulty,),
        instances_per_cell=1,
        solvers=("greedy-insertion",),
        algorithm_seeds=(42,),
        evaluation_budget=250,
    )
    generated, _ = generate_scenario(spec, size, difficulty, 0)
    tasks = tuple(
        task.model_copy(
            update={
                "target": Target(
                    target_id=task.target.target_id,
                    name=REFERENCE_TARGETS[index][0],
                    latitude_deg=REFERENCE_TARGETS[index][1],
                    longitude_deg=REFERENCE_TARGETS[index][2],
                ),
                "priority_value": _quantize(task.priority_value),
                "duration_s": _quantize(task.duration_s),
                "visibility_windows": tuple(
                    TimeWindow(
                        window_id=window.window_id,
                        start_s=_quantize(window.start_s),
                        end_s=_quantize(window.end_s),
                    )
                    for window in task.visibility_windows
                ),
                "required_attitude_deg": _quantize(task.required_attitude_deg),
                "energy_cost_wh": _quantize(task.energy_cost_wh),
                "storage_cost_gb": _quantize(task.storage_cost_gb),
            }
        )
        for index, task in enumerate(generated.tasks)
    )
    satellite = generated.satellite.model_copy(
        update={
            "energy_capacity_wh": _quantize(generated.satellite.energy_capacity_wh),
            "initial_energy_wh": _quantize(generated.satellite.initial_energy_wh),
            "recharge_rate_w": _quantize(generated.satellite.recharge_rate_w),
            "storage_capacity_gb": _quantize(generated.satellite.storage_capacity_gb),
            "initial_storage_gb": _quantize(generated.satellite.initial_storage_gb),
            "initial_attitude_deg": _quantize(generated.satellite.initial_attitude_deg),
            "slew_rate_deg_s": _quantize(generated.satellite.slew_rate_deg_s),
            "settling_time_s": _quantize(generated.satellite.settling_time_s),
        }
    )
    if scenario_id == "showcase-resources-10":
        total_storage_gb = sum(task.storage_cost_gb for task in tasks)
        satellite = satellite.model_copy(
            update={
                "storage_capacity_gb": _quantize(
                    satellite.initial_storage_gb + total_storage_gb * 0.65
                ),
            }
        )
    return generated.model_copy(
        update={
            "scenario_id": scenario_id,
            "name": research_question.removesuffix("?"),
            "satellite": satellite,
            "tasks": tasks,
            "metadata": {
                **generated.metadata,
                "purpose": "v0.2 comparative-methods showcase",
                "research_question": research_question,
                "numeric_precision_decimals": SHOWCASE_DECIMAL_PLACES,
                "geometry_note": (
                    "Targets use WGS84 reference coordinates; access windows are synthetic."
                ),
            },
        }
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    expected_files: set[Path] = set()
    for filename, scenario_id, size, difficulty, question in SHOWCASES:
        output = OUTPUT_DIR / filename
        expected_files.add(output)
        build_showcase(scenario_id, size, difficulty, question).to_json(output)

    for stale in OUTPUT_DIR.glob("*.json"):
        if stale not in expected_files:
            stale.unlink()


if __name__ == "__main__":
    main()
