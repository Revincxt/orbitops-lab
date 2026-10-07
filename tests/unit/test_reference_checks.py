from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from orbitops.web.reference_checks import (
    check_constraints,
    check_ellipsoid_visibility,
    transition_seconds,
)

ARCHIVE = Path(__file__).parents[2] / "data/eos-bench/reference.json"


def test_seven_plans_have_retained_attitudes_and_scoped_resource_results() -> None:
    archive = json.loads(ARCHIVE.read_text())
    ids = [p["plan_id"] for p in archive["plans"]]
    for name in ["mip", "ga", "aco"]:
        assert [i for i in ids if i.startswith(f"eos-{name}-")] == [f"eos-{name}-profit"]
    for plan in archive["plans"]:
        checked = check_constraints(archive["scenario"], plan["assignments"])
        assert checked == {
            k: v for k, v in plan["checks"]["constraints"].items() if k != "ellipsoid_visibility"
        }
        assert checked["attitude"]["status"] == "pass"
        assert checked["per_orbit_resources"]["status"] == "pass"
        assert not checked["missing"]
        assert checked["transitions"]["source_profile"] == "not recorded"
        assert checked["transitions"]["profiles"]["High"]["violations"]
        assert "battery dynamics" in checked["not_checked"]
        assert checked["full_feasibility"] == "not independently verified"


def test_constraints_detect_attitude_and_resource_tampering_without_changing_plan() -> None:
    archive = json.loads(ARCHIVE.read_text())
    assignments = deepcopy(archive["plans"][0]["assignments"])
    assignments[0]["sat_angles"]["roll_angles"][0] = 80
    assignments[0]["source_power_cost_w"] = 501
    assignments[0]["data_volume_gb"] = 1001
    original = deepcopy(assignments)
    result = check_constraints(archive["scenario"], assignments)
    assert result["attitude"]["status"] == result["per_orbit_resources"]["status"] == "fail"
    assert {v["code"] for v in result["per_orbit_resources"]["issues"]} == {
        "max_power_W",
        "max_data_storage_GB",
    }
    assert assignments == original


def test_missing_parameters_remain_unknown_instead_of_pass() -> None:
    archive = json.loads(ARCHIVE.read_text())
    a = deepcopy(archive["plans"][0]["assignments"][:2])
    a[0]["sat_angles"] = None
    a[0]["source_power_cost_w"] = None
    result = check_constraints(archive["scenario"], a)
    assert result["attitude"]["status"] == result["per_orbit_resources"]["status"] == "unknown"
    assert result["missing"]


def test_ellipsoid_visibility_distinguishes_real_access_from_far_side_targets() -> None:
    scenario = {
        "tasks": [
            {
                "task_id": "t",
                "target": {
                    "longitude_deg": 0,
                    "latitude_deg": 0,
                    "altitude_m": 0,
                },
            }
        ]
    }
    assignment = [{"task_id": "t", "satellite_id": "s", "start_s": 0, "end_s": 1}]
    visible = check_ellipsoid_visibility(scenario, assignment, {"s": [0, 0, 0, 500000]})
    assert visible["status"] == "pass" and visible["checked_samples"] == 1
    blocked = check_ellipsoid_visibility(scenario, assignment, {"s": [0, 180, 0, 500000]})
    assert blocked["status"] == "fail"
    assert blocked["issues"][0]["minimum_elevation_deg"] == pytest.approx(-90)


def test_default_source_geometry_disagreement_is_reported_without_rewriting_windows() -> None:
    archive = json.loads(ARCHIVE.read_text())
    plan = archive["plans"][0]
    geometry = plan["checks"]["constraints"]["ellipsoid_visibility"]
    assert geometry["status"] == "fail"
    assert geometry["checked_tasks"] == 488
    assert geometry["checked_samples"] == 4849
    assert (
        sum(
            issue["first_blocked_s"]
            == next(a["start_s"] for a in plan["assignments"] if a["task_id"] == issue["task_id"])
            for issue in geometry["issues"]
        )
        == 463
    )
    assert plan["source_metrics"]["TCR"] == 0.976
    assert not plan["checks"]["issues"]


@pytest.mark.parametrize(
    "delta,expected",
    [
        (0, 11.66),
        (10, 11.66),
        (11, 5 + 11 / 3),
        (30, 15),
        (31, 10 + 31 / 4),
        (60, 25),
        (61, 16 + 61 / 5),
        (90, 34),
        (91, 22 + 91 / 6),
    ],
)
def test_transition_piecewise_boundaries(delta: float, expected: float) -> None:
    assert transition_seconds(delta, "High") == pytest.approx(expected)
