"""Normalize pinned EOS-Bench data; verify Git blob hashes before importing.

No third-party code is executed. Source samples, IDs and task windows are retained.
The adapter never declares full scheduling feasibility or invents battery traces.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from orbitops.web.reference import ATTITUDE_DISPLAY
from orbitops.web.reference_checks import check_constraints, check_ellipsoid_visibility

REVISION = "ee282656e8b2f6fd0d3cf84677b40966e2780ef3"
SOURCE_TREE = "b90f537de42e65782372fd28a4c610da6922f90d"
SCENE = "Scenario_S1_Sats20_M500_T0.5d_dist0"
SOURCE_ROOT = f"https://github.com/Ethan19YQ/EOS-Bench/blob/{REVISION}/docs/"
PLANS = (
    (
        "eos-sa-balanced",
        "SA · balanced",
        "profit=.25 completion=.25 timeliness=.25 balance=.25",
        "c3_sa_p0.25_c0.25_t0.25_b0.25.json",
        "selected-plan.json",
    ),
    (
        "eos-sa-profit",
        "SA · profit",
        "profit=1 completion=0 timeliness=0 balance=0",
        "c3_sa_p1_c0_t0_b0.json",
        "plan-sa-profit.json",
    ),
    (
        "eos-greedy-profit",
        "Greedy · profit",
        "implicit profit-first",
        "c2_profit_first_implicit.json",
        "plan-greedy-profit.json",
    ),
    (
        "eos-ppo-profit",
        "PPO · profit",
        "profit=1 completion=0 timeliness=0 balance=0",
        "c4_ppo_ppo_model_p1_c0_t0_b0.json",
        "plan-ppo-profit.json",
    ),
    (
        "eos-mip-profit",
        "MIP · profit",
        "profit=1 completion=0 timeliness=0 balance=0",
        "c1_mip_p1_c0_t0_b0.json",
        "plan-mip-profit.json",
    ),
    (
        "eos-ga-profit",
        "GA · profit",
        "profit=1 completion=0 timeliness=0 balance=0",
        "c3_ga_p1_c0_t0_b0.json",
        "plan-ga-profit.json",
    ),
    (
        "eos-aco-profit",
        "ACO · profit",
        "profit=1 completion=0 timeliness=0 balance=0",
        "c3_aco_p1_c0_t0_b0.json",
        "plan-aco-profit.json",
    ),
)


def utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    # EOS's generator treats these legacy naive timestamps as UTC.
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def read_source(path: Path, name: str, tree: dict[str, str]) -> tuple[Any, dict[str, Any]]:
    raw = path.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    expected = tree[f"docs/{name}"]
    if blob != expected:
        raise ValueError(f"incomplete or unpinned source: {name}: {blob} != {expected}")
    return json.loads(raw), {
        "filename": name,
        "url": SOURCE_ROOT + name,
        "bytes": len(raw),
        "git_blob_sha1": blob,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def check_plan(scenario: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    epoch = utc(scenario["epoch_utc"])
    horizon = scenario["horizon_end_s"]
    tasks = {t["task_id"]: t for t in scenario["tasks"]}
    sats = {s["satellite_id"] for s in scenario["satellites"]}
    assignments, issues, seen = [], [], set()

    def issue(code: str, tid: str, message: str) -> None:
        issues.append({"code": code, "task_id": tid, "message": message, "severity": "error"})

    for item in source["assignments"]:
        tid, sid = item["task_id"], item["satellite_id"]
        if tid not in tasks or sid not in sats:
            raise ValueError("source assignment references an unknown task or satellite")
        start = (utc(item["sat_start_time"]) - epoch).total_seconds()
        end = (utc(item["sat_end_time"]) - epoch).total_seconds()
        if tid in seen:
            issue("duplicate_task", tid, "Task is assigned more than once.")
        seen.add(tid)
        if not 0 <= start < end <= horizon:
            issue("outside_horizon", tid, "Execution interval is outside the source horizon.")
        if end - start + 1e-6 < tasks[tid]["duration_s"]:
            issue("duration", tid, "Source execution is shorter than required duration.")
        matches = [
            w
            for w in tasks[tid]["visibility_windows"]
            if w["satellite_id"] == sid
            and w["start_s"] <= start + 1e-6
            and end <= w["end_s"] + 1e-6
        ]
        if not matches:
            issue("source_window", tid, "No containing source observation window was found.")
        elif not any(
            (item.get("sensor_id") is None or item["sensor_id"] == w["sensor_id"])
            and (item.get("orbit_number") is None or item["orbit_number"] == w["orbit_number"])
            for w in matches
        ):
            issue("window_metadata", tid, "Assignment sensor/orbit differs from source window.")
        assignments.append(
            {
                "task_id": tid,
                "satellite_id": sid,
                "start_s": start,
                "end_s": end,
                "window_id": matches[0]["window_id"] if matches else None,
                "sensor_id": item.get("sensor_id"),
                "orbit_number": item.get("orbit_number"),
                "data_volume_gb": item.get("data_volume_GB"),
                "source_power_cost_w": item.get("power_cost_W"),
                "sat_angles": item.get("sat_angles"),
            }
        )
    assignments.sort(key=lambda a: (a["start_s"], a["satellite_id"], a["task_id"]))
    for sid in sorted(sats):
        previous = None
        for a in (a for a in assignments if a["satellite_id"] == sid):
            if previous is not None and a["start_s"] < previous["end_s"] - 1e-6:
                issue(
                    "satellite_overlap", a["task_id"], f"Overlaps {previous['task_id']} on {sid}."
                )
            if previous is None or a["end_s"] > previous["end_s"]:
                previous = a
    unassigned = sorted(set(tasks) - seen)
    if set(source.get("unassigned_tasks", [])) != set(unassigned):
        issue("unassigned_partition", "", "Source unassigned list differs from the task partition.")
    loads = {
        sid: sum(a["end_s"] - a["start_s"] for a in assignments if a["satellite_id"] == sid)
        for sid in sorted(sats)
    }
    total_required = sum(t["duration_s"] for t in tasks.values())
    mean = sum(loads.values()) / len(sats)
    metric = {
        "TP": sum(tasks[tid]["priority_value"] for tid in sorted(seen)),
        "TCR": len(seen) / len(tasks),
        "TM": (sum(a["start_s"] for a in assignments) + len(unassigned) * horizon)
        / (len(tasks) * horizon),
        "BD": max(0, min(1, 1 - sum(abs(w - mean) for w in loads.values()) / (2 * total_required))),
    }
    for key, value in metric.items():
        if not math.isclose(value, source["metrics"][key], rel_tol=1e-9, abs_tol=1e-9):
            issue(
                "metric_mismatch", "", f"{key}: source={source['metrics'][key]}, recomputed={value}"
            )
    return {
        "assignments": assignments,
        "unassigned_tasks": unassigned,
        "source_metrics": source["metrics"],
        "recomputed_metrics": metric,
        "workloads": loads,
        "checks": {
            "issues": issues,
            "checked": [
                "IDs",
                "task uniqueness",
                "horizon",
                "duration",
                "source window containment",
                "satellite observation overlap",
                "task partition",
                "TP/TCR/TM/BD reconciliation",
            ],
            "not_checked": [
                "sensor geometry",
                "battery dynamics",
                "downlink",
            ],
            "full_feasibility": "not independently verified",
            "constraints": check_constraints(scenario, assignments),
        },
    }


def build(source_dir: Path, stride: int = 30, chunk_dir: Path | None = None) -> dict[str, Any]:
    if stride < 1:
        raise ValueError("sample stride must be positive")
    if chunk_dir is None:
        raise ValueError("chunk_dir is required to preserve the full 1-second source ephemeris")
    source_tree = json.loads((source_dir / "tree.json").read_text())
    if source_tree["sha"] not in {REVISION, SOURCE_TREE} or source_tree.get("truncated"):
        raise ValueError("source tree is incomplete or not pinned to the expected revision")
    tree = {x["path"]: x["sha"] for x in source_tree["tree"]}
    source, manifest = read_source(
        source_dir / "source-scenario-complete.json", SCENE + ".json", tree
    )
    epoch = utc(source["metadata"]["creation_time"])
    satellites = [
        {
            "satellite_id": s["id"],
            "orbital_params": s["orbital_params"],
            "satellite_specs": s["satellite_specs"],
            "sensors": s["observation_capability"]["sensors"],
            "maneuverability": s["maneuverability_capability"],
        }
        for s in source["satellites"]
    ]
    tasks = {
        m["id"]: {
            "task_id": m["id"],
            "target": {
                "target_id": m["id"],
                "name": m["id"],
                "latitude_deg": m["target_location"]["latitude"],
                "longitude_deg": m["target_location"]["longitude"],
                "altitude_m": m["target_location"].get("altitude_km", 0) * 1000,
            },
            "priority_value": m["priority"],
            "duration_s": m["observation_requirement"]["duration_s"],
            "visibility_windows": [],
        }
        for m in source["missions"]
    }
    counter = 0
    for ow in source["observation_windows"]:
        for w in ow["time_windows"]:
            counter += 1
            tasks[ow["mission_id"]]["visibility_windows"].append(
                {
                    "window_id": f"eos-window-{counter}",
                    "satellite_id": ow["satellite_id"],
                    "sensor_id": ow["sensor_id"],
                    "start_s": (utc(w["start_time"]) - epoch).total_seconds(),
                    "end_s": (utc(w["end_time"]) - epoch).total_seconds(),
                    "orbit_number": w.get("orbit_number"),
                }
            )
    scenario = {
        "scenario_id": "eos-s1-20-500",
        "source_scenario_id": source["scenario_id"],
        "name": "EOS-Bench · 20 satellites / 500 tasks",
        "epoch_utc": epoch.isoformat().replace("+00:00", "Z"),
        "horizon_start_s": 0,
        "horizon_end_s": source["metadata"]["duration"],
        "satellite": {"satellite_id": satellites[0]["satellite_id"]},
        "satellites": satellites,
        "tasks": list(tasks.values()),
        "metadata": {
            "geometry_note": (
                "Source Orekit Keplerian orbits; source visibility windows, not telemetry."
            )
        },
    }
    packets, orbit_manifest = read_source(
        source_dir / "source-orbit-complete.czml", "orbit.czml", tree
    )
    orbits = []
    for packet in packets:
        if "path" not in packet:
            continue
        values = packet["position"]["cartographicDegrees"]
        samples = [values[i : i + 4] for i in range(0, len(values), 4 * stride)]
        if samples[-1] != values[-4:]:
            samples.append(values[-4:])
        orbits.append(
            {
                "satellite_id": packet["id"],
                "epoch_utc": packet["position"]["epoch"],
                "period_s": packet["path"]["trailTime"],
                "samples": samples,
            }
        )
    if {o["satellite_id"] for o in orbits} != {s["satellite_id"] for s in satellites}:
        raise ValueError("orbit and scenario satellite identities differ")
    for orbit in orbits:
        if (
            utc(orbit["epoch_utc"]) != epoch
            or orbit["samples"][0][0] != 0
            or orbit["samples"][-1][0] != scenario["horizon_end_s"]
        ):
            raise ValueError("source orbit epoch or horizon differs from scenario")
    chunks = []
    if chunk_dir is not None:
        chunk_dir.mkdir(parents=True, exist_ok=True)
        satellite_packets = [p for p in packets if "path" in p]
        horizon = int(scenario["horizon_end_s"])
        for packet in satellite_packets:
            values = packet["position"]["cartographicDegrees"]
            if len(values) != (horizon + 1) * 4 or any(
                values[i * 4] != i for i in range(horizon + 1)
            ):
                raise ValueError("expected complete 1-second source ephemeris")
        for start in range(0, horizon, 3600):
            end = min(start + 3600, horizon)
            chunk = {
                "schema_version": "eos-orbit-chunk-1",
                "epoch_utc": scenario["epoch_utc"],
                "frame": "WGS84 geodetic",
                "start_s": start,
                "end_s": end,
                "step_s": 1,
                "orbits": [],
            }
            for packet in satellite_packets:
                values = packet["position"]["cartographicDegrees"]
                chunk["orbits"].append(
                    {
                        "satellite_id": packet["id"],
                        "cartographic_degrees": [
                            values[i * 4 + j] for i in range(start, end + 1) for j in (1, 2, 3)
                        ],
                    }
                )
            raw = (json.dumps(chunk, separators=(",", ":"), allow_nan=False) + "\n").encode()
            filename = f"{start:05d}.json"
            (chunk_dir / filename).write_bytes(raw)
            chunks.append(
                {
                    "filename": filename,
                    "start_s": start,
                    "end_s": end,
                    "bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            )
    manifests = [manifest, orbit_manifest]
    source_positions = {
        p["id"]: p["position"]["cartographicDegrees"] for p in packets if "path" in p
    }
    plans = []
    for pid, label, objective, suffix, local in PLANS:
        original, record = read_source(source_dir / local, f"scheduler_{SCENE}_{suffix}", tree)
        if original["scenario_id"] != source["scenario_id"]:
            raise ValueError("source plan scenario identity differs from scenario")
        if (
            utc(original["start_time"]) != epoch
            or (utc(original["end_time"]) - epoch).total_seconds() != scenario["horizon_end_s"]
        ):
            raise ValueError("source plan time horizon differs from scenario")
        plans.append(
            {
                "plan_id": pid,
                "label": label,
                "objective": objective,
                "source_file": record,
                **check_plan(scenario, original),
            }
        )
        plans[-1]["checks"]["constraints"]["ellipsoid_visibility"] = check_ellipsoid_visibility(
            scenario, plans[-1]["assignments"], source_positions
        )
        manifests.append(record)
    return {
        "schema_version": "eos-reference-1",
        "scenario": scenario,
        "plans": plans,
        "replay": {
            "model": "Source Orekit Keplerian propagation",
            "frame": "WGS84 geodetic",
            "orbits": orbits,
            "sample_stride": stride,
            "attitude": {
                "declared_frame": "EME2000",
                "rotation_order": "ZYX",
                "convention": "FRAME_TRANSFORM",
                "sample_step_s": 1,
                "frame_verified": False,
                **ATTITUDE_DISPLAY,
                "availability": "scheduled observation intervals only",
            },
            "ephemeris": {"step_s": 1, "chunk_duration_s": 3600, "chunks": chunks},
            "interpolation": (
                "3D: linear Cartesian; 2D: date-line-aware geodetic interpolation. "
                "Retained source samples; visualization only."
            ),
        },
        "provenance": {
            "repository": "https://github.com/Ethan19YQ/EOS-Bench",
            "revision": REVISION,
            "files": manifests,
            "source_time_assumption": (
                "Legacy naive source timestamps interpreted as UTC, matching EOS generator."
            ),
            "data_kind": "simulation benchmark, not operational telemetry",
            "window_count": counter,
            "omitted": (
                "Unscheduled per-window attitude arrays; 8 other published plans. "
                "Scheduled sat_angles and complete 1-second orbital positions retained. "
                "No values synthesized."
            ),
            "license_status": (
                "No repository license declaration found in the pinned tree; "
                "review before redistribution."
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/eos-bench/reference.json"))
    args = parser.parse_args()
    artifact = build(args.source_dir, chunk_dir=args.output.parent / "orbits")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raw = (
        json.dumps(artifact, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")
    args.output.write_bytes(raw)
    args.output.with_suffix(".sha256").write_text(hashlib.sha256(raw).hexdigest() + "\n")
    print(
        f"Imported {len(artifact['scenario']['satellites'])} satellites, "
        f"{len(artifact['scenario']['tasks'])} tasks, {len(artifact['plans'])} plans; "
        f"{args.output.stat().st_size} bytes"
    )
    for plan in artifact["plans"]:
        print(plan["plan_id"], plan["recomputed_metrics"], "issues:", len(plan["checks"]["issues"]))


if __name__ == "__main__":
    main()
