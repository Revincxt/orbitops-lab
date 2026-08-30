from pathlib import Path

from orbitops.domain.models import Scenario

from scripts.build_showcase_scenarios import (
    OUTPUT_DIR,
    SHOWCASE_DECIMAL_PLACES,
    SHOWCASES,
    build_showcase,
)


def test_committed_showcases_are_reproducible_and_cover_declared_scales() -> None:
    observed_counts: list[int] = []

    for filename, scenario_id, size, difficulty, question in SHOWCASES:
        path = OUTPUT_DIR / filename
        assert path.is_file()
        committed = Scenario.from_json(path)
        regenerated = build_showcase(scenario_id, size, difficulty, question)

        assert committed == regenerated
        observed_counts.append(len(committed.tasks))
        assert committed.metadata["research_question"] == question
        assert committed.metadata["numeric_precision_decimals"] == SHOWCASE_DECIMAL_PLACES
        assert all(task.target.name != task.target.target_id for task in committed.tasks)

    assert observed_counts == [6, 10, 18, 30]
    assert {path.name for path in Path(OUTPUT_DIR).glob("*.json")} == {
        entry[0] for entry in SHOWCASES
    }


def test_showcase_labels_have_matching_stressors_and_scope_notes() -> None:
    scenarios = {
        scenario.scenario_id: scenario
        for scenario in (Scenario.from_json(OUTPUT_DIR / entry[0]) for entry in SHOWCASES)
    }

    temporal = scenarios["showcase-temporal-06"]
    windows = [window for task in temporal.tasks for window in task.visibility_windows]
    assert any(
        left.start_s < right.end_s and right.start_s < left.end_s
        for index, left in enumerate(windows)
        for right in windows[index + 1 :]
    )

    resources = scenarios["showcase-resources-10"]
    storage_available = (
        resources.satellite.storage_capacity_gb - resources.satellite.initial_storage_gb
    )
    energy_upper_bound = resources.satellite.initial_energy_wh + (
        resources.satellite.recharge_rate_w
        * (resources.horizon_end_s - resources.horizon_start_s)
        / 3600
    )
    assert sum(task.storage_cost_gb for task in resources.tasks) > storage_available
    assert sum(task.energy_cost_wh for task in resources.tasks) > energy_upper_bound

    slew = scenarios["showcase-slew-18"]
    attitudes = [task.required_attitude_deg for task in slew.tasks]
    assert max(attitudes) - min(attitudes) > 140
    assert "lexicographic value-first" in slew.metadata["research_question"]

    global_scenario = scenarios["showcase-global-30"]
    latitudes = [task.target.latitude_deg for task in global_scenario.tasks]
    longitudes = [task.target.longitude_deg for task in global_scenario.tasks]
    assert min(latitudes) < -30 < 60 < max(latitudes)
    assert min(longitudes) < -150 < 150 < max(longitudes)
    assert global_scenario.metadata["geometry_note"] == (
        "Targets use WGS84 reference coordinates; access windows are synthetic."
    )
