from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from itertools import pairwise
from pathlib import Path

import pytest
from orbitops.solvers.registry import get_solver
from orbitops.web import LabApplication
from orbitops.web.evaluation import evaluation_metrics
from orbitops.web.reference import ReferenceArchive

from scripts.import_eos_reference import REVISION, check_plan, read_source, utc
from tests.factories import make_seeded_scenario

ROOT = Path(__file__).parents[2]
ARCHIVE = ROOT / "data" / "eos-bench" / "reference.json"


@pytest.fixture(scope="module")
def archive() -> dict:
    return json.loads(ARCHIVE.read_text())


def test_reference_keeps_source_identity_time_and_provenance(archive: dict) -> None:
    scenario = archive["scenario"]
    assert len(scenario["satellites"]) == 20
    assert len(scenario["tasks"]) == 500
    assert sum(len(t["visibility_windows"]) for t in scenario["tasks"]) == 4035
    assert scenario["epoch_utc"] == "2025-11-18T12:00:00Z"
    assert scenario["horizon_end_s"] == 43200
    assert archive["provenance"]["revision"] == REVISION
    assert len(archive["provenance"]["files"]) == 6
    assert all(len(f["sha256"]) == 64 for f in archive["provenance"]["files"])
    assert "not operational telemetry" in archive["provenance"]["data_kind"]


@pytest.mark.parametrize(
    "index, count, profit", [(0, 488, 2816), (1, 493, 2833), (2, 412, 2568), (3, 492, 2832)]
)
def test_reference_metrics_and_intervals_reconcile(
    archive: dict, index: int, count: int, profit: int
) -> None:
    scenario = archive["scenario"]
    plan = archive["plans"][index]
    tasks = {t["task_id"]: t for t in scenario["tasks"]}
    assert len(plan["assignments"]) == count
    assert len(plan["unassigned_tasks"]) == 500 - count
    assert not plan["checks"]["issues"]
    assert plan["recomputed_metrics"]["TP"] == profit
    assert plan["recomputed_metrics"]["TCR"] == count / 500
    for key in ["TP", "TCR", "TM", "BD"]:
        assert plan["recomputed_metrics"][key] == pytest.approx(plan["source_metrics"][key])
    for assignment in plan["assignments"]:
        task = tasks[assignment["task_id"]]
        assert assignment["end_s"] - assignment["start_s"] >= task["duration_s"]
        assert any(
            w["satellite_id"] == assignment["satellite_id"]
            and w["start_s"] <= assignment["start_s"] < assignment["end_s"] <= w["end_s"]
            for w in task["visibility_windows"]
        )
        assert "energy_after_wh" not in assignment


def test_reference_orbits_cover_the_same_epoch_horizon_and_satellites(archive: dict) -> None:
    assert {o["satellite_id"] for o in archive["replay"]["orbits"]} == {
        s["satellite_id"] for s in archive["scenario"]["satellites"]
    }
    for orbit in archive["replay"]["orbits"]:
        samples = orbit["samples"]
        assert len(samples) == 1441
        assert samples[0][0] == 0
        assert samples[-1][0] == 43200
        assert all(a[0] < b[0] for a, b in pairwise(samples))
        assert all(-180 <= s[1] <= 180 and -90 <= s[2] <= 90 and s[3] > 0 for s in samples)
        assert utc(orbit["epoch_utc"]) == utc(archive["scenario"]["epoch_utc"])


def test_reference_is_not_a_full_feasibility_certificate() -> None:
    reference = ReferenceArchive(ARCHIVE)
    payload = reference.payload("eos-sa-balanced")
    assert payload["result"]["validation"]["is_feasible"] is None
    assert payload["result"]["validation"]["reference_consistent"] is True
    assert "battery dynamics" in payload["reference_plan"]["checks"]["not_checked"]
    assert payload["run_metadata"]["seed"] == "not recorded"
    assert payload["result"]["metrics"]["total_slew_time_s"] is None


def test_modified_archive_is_rejected_instead_of_reusing_stored_verdict(tmp_path: Path) -> None:
    raw = ARCHIVE.read_bytes()
    path = tmp_path / "reference.json"
    path.write_bytes(raw)
    path.with_suffix(".sha256").write_text(hashlib.sha256(raw).hexdigest())
    assert ReferenceArchive(path).data is not None
    path.write_bytes(raw + b" ")
    with pytest.raises(ValueError, match="integrity check failed"):
        ReferenceArchive(path)


def test_source_consistency_checks_detect_duplicate_tasks(archive: dict) -> None:
    scenario = archive["scenario"]
    plan = archive["plans"][0]
    epoch = utc(scenario["epoch_utc"])
    assignments = [
        {
            "task_id": a["task_id"],
            "satellite_id": a["satellite_id"],
            "sat_start_time": (epoch + timedelta(seconds=a["start_s"])).isoformat(),
            "sat_end_time": (epoch + timedelta(seconds=a["end_s"])).isoformat(),
        }
        for a in plan["assignments"]
    ]
    source = {
        "assignments": assignments,
        "unassigned_tasks": plan["unassigned_tasks"],
        "metrics": plan["source_metrics"],
    }
    assert not check_plan(scenario, source)["checks"]["issues"]
    source["assignments"].append(assignments[0])
    assert "duplicate_task" in {
        issue["code"] for issue in check_plan(scenario, source)["checks"]["issues"]
    }


def test_reference_api_is_read_only_and_cannot_enter_local_solver_contract() -> None:
    app = LabApplication(ROOT / "scenarios")
    assert app.dispatch("GET", "/api/reference").status == 200
    assert app.dispatch("GET", "/api/reference/runs/eos-sa-balanced").status == 200
    assert app.dispatch("GET", "/api/reference/runs/not-found").status == 404
    response = app.dispatch(
        "POST",
        "/api/solve",
        json.dumps({"scenario_id": "eos-s1-20-500", "solver_name": "greedy-insertion"}).encode(),
    )
    assert response.status == 400
    assert "unknown scenario" in json.loads(response.body)["error"]


def test_source_hash_check_rejects_modified_or_truncated_data(tmp_path: Path) -> None:
    path = tmp_path / "source.json"
    raw = b'{"value": 1}'
    path.write_bytes(raw)
    sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    assert read_source(path, "source.json", {"docs/source.json": sha})[0] == {"value": 1}
    path.write_bytes(raw[:-1])
    with pytest.raises(ValueError, match="incomplete or unpinned"):
        read_source(path, "source.json", {"docs/source.json": sha})


def test_legacy_source_times_are_explicitly_normalized_to_utc() -> None:
    assert utc("2025-11-18T12:00:00") == utc("2025-11-18T20:00:00+08:00")
    assert utc("2025-11-18T12:00:00").utcoffset().total_seconds() == 0


def test_local_evaluation_keeps_single_satellite_balance_not_applicable() -> None:
    scenario = make_seeded_scenario(seed=42, task_count=6)
    result = get_solver("greedy-insertion").solve(scenario)
    metric = evaluation_metrics(scenario, result)
    assert metric["BD"] is None
    assert metric["TP"] == pytest.approx(result.metrics.total_value)
    assert metric["TCR"] == result.metrics.completed_tasks / len(scenario.tasks)
    assert 0 <= metric["TM"] <= 1
    assert metric["RT"] == result.runtime_s
