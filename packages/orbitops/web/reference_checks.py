"""Independent, scoped checks of retained EOS benchmark parameters.

The source's per-orbit sum of power_cost_W is a scheduler budget, not energy.
Agility profiles are evaluated separately because the published run omits its profile.
"""

from __future__ import annotations

import math
from collections import defaultdict
from itertools import pairwise
from typing import Any

AXES = ("pitch", "yaw", "roll")
PROFILES = {
    "High": (3.0, 4.0, 5.0, 6.0),
    "Standard": (1.5, 2.0, 2.5, 3.0),
    "Low": (0.75, 1.0, 1.25, 1.5),
    "Limited": (0.5, 0.67, 0.83, 1.0),
}


def check_ellipsoid_visibility(
    scenario: dict[str, Any],
    assignments: list[dict[str, Any]],
    ephemeris: dict[str, list[float]],
) -> dict[str, Any]:
    """Check source 1-second assignment samples against WGS84's local horizon.

    This is independent geometric evidence, not source-window containment or
    terrain/sensor access certification. All inputs and original plans stay intact.
    """
    targets = {t["task_id"]: t["target"] for t in scenario["tasks"]}
    issues = []
    checked = 0
    radius = 6378137.0
    eccentricity2 = (1 / 298.257223563) * (2 - 1 / 298.257223563)

    def cartesian(lon: float, lat: float, altitude: float) -> tuple[float, float, float]:
        phi, longitude = math.radians(lat), math.radians(lon)
        n = radius / math.sqrt(1 - eccentricity2 * math.sin(phi) ** 2)
        return (
            (n + altitude) * math.cos(phi) * math.cos(longitude),
            (n + altitude) * math.cos(phi) * math.sin(longitude),
            (n * (1 - eccentricity2) + altitude) * math.sin(phi),
        )

    for a in assignments:
        target = targets[a["task_id"]]
        ground = cartesian(target["longitude_deg"], target["latitude_deg"], target["altitude_m"])
        phi, longitude = math.radians(target["latitude_deg"]), math.radians(target["longitude_deg"])
        normal = (
            math.cos(phi) * math.cos(longitude),
            math.cos(phi) * math.sin(longitude),
            math.sin(phi),
        )
        values = ephemeris[a["satellite_id"]]
        minimum, first_blocked = 90.0, None
        for time in range(math.ceil(a["start_s"]), math.ceil(a["end_s"])):
            offset = time * 4
            if values[offset] != time:
                raise ValueError("visibility check requires complete 1-second source positions")
            position = cartesian(*values[offset + 1 : offset + 4])
            line = tuple(x - y for x, y in zip(position, ground, strict=True))
            elevation = math.degrees(
                math.asin(
                    max(
                        -1.0,
                        min(
                            1.0,
                            sum(x * y for x, y in zip(line, normal, strict=True))
                            / math.hypot(*line),
                        ),
                    )
                )
            )
            minimum = min(minimum, elevation)
            checked += 1
            if elevation < -1e-6 and first_blocked is None:
                first_blocked = time
        if first_blocked is not None:
            issues.append(
                {
                    "task_id": a["task_id"],
                    "satellite_id": a["satellite_id"],
                    "code": "earth_occlusion",
                    "first_blocked_s": first_blocked,
                    "minimum_elevation_deg": minimum,
                }
            )
    return {
        "status": "fail" if issues else "pass",
        "checked_samples": checked,
        "checked_tasks": len(assignments),
        "issues": issues,
        "scope": "WGS84 local-horizon check at original 1-second assignment samples; "
        "not terrain, refraction, source sensor coverage or full feasibility.",
    }


def transition_seconds(delta: float, profile: str) -> float:
    """EOS's published piecewise agile transition model (degrees, seconds)."""
    rates = PROFILES[profile]
    if delta <= 10:
        return 11.66
    for boundary, overhead, rate in zip((30, 60, 90), (5, 10, 16), rates, strict=False):
        if delta <= boundary:
            return overhead + delta / rate
    return 22 + delta / rates[3]


def check_constraints(
    scenario: dict[str, Any], assignments: list[dict[str, Any]]
) -> dict[str, Any]:
    satellites = {s["satellite_id"]: s for s in scenario["satellites"]}
    groups: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    timelines: dict[str, list[dict[str, Any]]] = defaultdict(list)
    attitude_issues, resource_issues, missing = [], [], []
    valid_angles = set()
    for a in assignments:
        sid, tid = a["satellite_id"], a["task_id"]
        timelines[sid].append(a)
        if a.get("orbit_number") is not None:
            groups[(sid, a["orbit_number"])].append(a)
        else:
            missing.append({"task_id": tid, "field": "orbit_number"})
        angles = a.get("sat_angles") or {}
        count = math.ceil(a["end_s"] - a["start_s"])
        capability = satellites[sid].get("maneuverability", {})
        valid = True
        for axis in AXES:
            values = angles.get(f"{axis}_angles")
            if not isinstance(values, list) or len(values) != count or not values:
                missing.append({"task_id": tid, "field": f"{axis}_angles"})
                valid = False
                continue
            if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
                attitude_issues.append({"task_id": tid, "code": "nonfinite_attitude", "axis": axis})
                valid = False
                continue
            limit = capability.get(f"max_{axis}_angle_deg")
            if limit is not None and max(abs(v) for v in values) > limit + 1e-6:
                attitude_issues.append({"task_id": tid, "code": "attitude_limit", "axis": axis})
        if valid:
            valid_angles.add(tid)
    budgets = []
    for (sid, number), items in sorted(groups.items()):
        specs = satellites[sid].get("satellite_specs", {})
        record: dict[str, Any] = {
            "satellite_id": sid,
            "orbit_number": number,
            "task_count": len(items),
        }
        for field, limit_key in (
            ("data_volume_gb", "max_data_storage_GB"),
            ("source_power_cost_w", "max_power_W"),
        ):
            values = [a.get(field) for a in items]
            limit = specs.get(limit_key)
            if limit is None or not all(
                isinstance(v, (int, float)) and math.isfinite(v) and v >= 0 for v in values
            ):
                missing.append({"satellite_id": sid, "orbit_number": number, "field": field})
                record[field] = None
                continue
            total = sum(values)
            record[field] = total
            record[limit_key] = limit
            if total > limit + 1e-9:
                resource_issues.append(
                    {
                        "satellite_id": sid,
                        "orbit_number": number,
                        "code": limit_key,
                        "used": total,
                        "limit": limit,
                    }
                )
        budgets.append(record)
    profiles: dict[str, dict[str, Any]] = {
        name: {"checked_pairs": 0, "violations": []} for name in PROFILES
    }
    missing_pairs = 0
    for sid, items in sorted(timelines.items()):
        ordered = sorted(items, key=lambda a: (a["start_s"], a["end_s"]))
        for previous, current in pairwise(ordered):
            if previous["task_id"] not in valid_angles or current["task_id"] not in valid_angles:
                missing_pairs += 1
                continue
            delta = sum(
                abs(
                    current["sat_angles"][f"{axis}_angles"][0]
                    - previous["sat_angles"][f"{axis}_angles"][-1]
                )
                for axis in AXES
            )
            gap = current["start_s"] - previous["end_s"]
            for name, result in profiles.items():
                result["checked_pairs"] += 1
                required = transition_seconds(delta, name)
                if gap + 1e-6 < required:
                    result["violations"].append(
                        {
                            "satellite_id": sid,
                            "previous_task_id": previous["task_id"],
                            "task_id": current["task_id"],
                            "gap_s": gap,
                            "required_s": required,
                            "delta_g_deg": delta,
                        }
                    )
    for result in profiles.values():
        result["status"] = (
            "fail" if result["violations"] else "unknown" if missing_pairs else "pass"
        )
    return {
        "attitude": {
            "status": "fail"
            if attitude_issues
            else "pass"
            if len(valid_angles) == len(assignments)
            else "unknown",
            "scope": (
                "Sample completeness, finite values and configured Euler limits only; "
                "coordinate frame not verified."
            ),
            "checked_tasks": len(valid_angles),
            "issues": attitude_issues,
        },
        "per_orbit_resources": {
            "status": "fail"
            if resource_issues
            else "unknown"
            if any(
                m["field"] in {"orbit_number", "data_volume_gb", "source_power_cost_w"}
                for m in missing
            )
            else "pass",
            "budgets": budgets,
            "issues": resource_issues,
            "power_basis": (
                "Sum of source power_cost_W per satellite/orbit against max_power_W; "
                "not Wh, battery state or instantaneous power."
            ),
        },
        "transitions": {
            "status": "conditional",
            "model": "EOS piecewise delta_g = sum of absolute endpoint Euler differences",
            "source_profile": "not recorded",
            "missing_pairs": missing_pairs,
            "profiles": profiles,
        },
        "missing": missing,
        "not_checked": [
            "battery dynamics",
            "downlink",
            "terrain and source sensor geometry",
            "within-task angular velocity",
            "real spacecraft attitude dynamics",
        ],
        "full_feasibility": "not independently verified",
    }
