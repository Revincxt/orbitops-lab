from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from itertools import pairwise
from pathlib import Path

import pytest
from orbitops.web import LabApplication
from orbitops.web.reference import ReferenceArchive

from scripts.import_eos_reference import REVISION, check_plan, read_source, utc

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
    assert len(archive["provenance"]["files"]) == 9
    assert all(len(f["sha256"]) == 64 for f in archive["provenance"]["files"])
    assert "not operational telemetry" in archive["provenance"]["data_kind"]


@pytest.mark.parametrize(
    "index, count, profit",
    [
        (0, 488, 2816),
        (1, 493, 2833),
        (2, 412, 2568),
        (3, 492, 2832),
        (4, 355, 2271),
        (5, 488, 2816),
        (6, 488, 2816),
    ],
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


def test_precise_chunks_preserve_all_satellites_samples_and_shared_boundaries(
    archive: dict,
) -> None:
    entries = archive["replay"]["ephemeris"]["chunks"]
    assert len(entries) == 12
    reference = ReferenceArchive(ARCHIVE)
    previous = None
    for entry in entries:
        raw = reference.orbit_chunk(entry["filename"])
        assert len(raw) == entry["bytes"] < 25 * 1024 * 1024
        chunk = json.loads(raw)
        assert chunk["step_s"] == 1
        assert chunk["end_s"] - chunk["start_s"] == 3600
        assert chunk["epoch_utc"] == archive["scenario"]["epoch_utc"]
        orbits = {o["satellite_id"]: o["cartographic_degrees"] for o in chunk["orbits"]}
        assert set(orbits) == {o["satellite_id"] for o in archive["replay"]["orbits"]}
        for orbit in archive["replay"]["orbits"]:
            values = orbits[orbit["satellite_id"]]
            assert len(values) == 3601 * 3
            for sample in orbit["samples"]:
                if chunk["start_s"] <= sample[0] <= chunk["end_s"]:
                    offset = int(sample[0] - chunk["start_s"]) * 3
                    assert values[offset : offset + 3] == sample[1:]
            if previous:
                assert previous[orbit["satellite_id"]][-3:] == values[:3]
        previous = orbits


def test_chunk_routes_only_serve_manifest_listed_integrity_checked_files(tmp_path: Path) -> None:
    app = LabApplication(ARCHIVE)
    assert app.dispatch("GET", "/orbit-data/00000.json").status == 200
    for route in [
        "/orbit-data/../reference.json",
        "/orbit-data/%2e%2e/reference.json",
        "/orbit-data/reference.sha256",
        "/orbit-data/99999.json",
    ]:
        assert app.dispatch("GET", route).status == 404
    for script in ["orbit-ephemeris.js", "satellite-attitude.js"]:
        assert app.dispatch("GET", "/" + script).status == 200
    copied = tmp_path / "reference.json"
    copied.write_bytes(ARCHIVE.read_bytes())
    copied.with_suffix(".sha256").write_bytes(ARCHIVE.with_suffix(".sha256").read_bytes())
    (tmp_path / "orbits").mkdir()
    (tmp_path / "orbits/00000.json").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="integrity check failed"):
        ReferenceArchive(copied).orbit_chunk("00000.json")


def test_reference_is_not_a_full_feasibility_certificate() -> None:
    reference = ReferenceArchive(ARCHIVE)
    exported = reference.export()
    assert exported is not None
    plan = exported["plans"][0]
    assert plan["checks"]["full_feasibility"] == "not independently verified"
    assert not plan["checks"]["issues"]
    assert "battery dynamics" in plan["checks"]["not_checked"]
    assert exported["replay"]["attitude"]["frame_verified"] is False
    assert "energy_after_wh" not in plan["assignments"][0]


def test_api_and_static_exports_describe_source_attitude_replay_without_changing_archive() -> None:
    reference = ReferenceArchive(ARCHIVE)
    original = json.dumps(reference.data, sort_keys=True)
    payload = json.loads(LabApplication(ARCHIVE).dispatch("GET", "/api/reference/data").body)
    exported = reference.export()
    assert exported is not None
    for replay in [payload["replay"], exported["replay"]]:
        assert "Source Euler replay" in replay["attitude"]["rendering"]
        assert "SLERP" in replay["attitude"]["sample_interpolation"]
        assert replay["attitude"]["max_display_off_nadir_deg"] == 29.5
        assert "preserve raw Euler arrays" in replay["attitude"]["display_correction"]
        assert replay["attitude"]["frame_verified"] is False
    assert json.dumps(reference.data, sort_keys=True) == original
    assert payload["plans"][0]["assignments"] == exported["plans"][0]["assignments"]


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
    app = LabApplication(ARCHIVE)
    assert app.dispatch("GET", "/api/reference/data").status == 200
    assert app.dispatch("GET", "/api/reference").status == 404
    assert app.dispatch("GET", "/api/reference/runs/eos-sa-balanced").status == 404
    assert app.dispatch("GET", "/api/reference/runs/not-found").status == 404
    response = app.dispatch(
        "POST",
        "/api/solve",
    )
    assert response.status == 405
    assert "read-only" in json.loads(response.body)["error"]


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
