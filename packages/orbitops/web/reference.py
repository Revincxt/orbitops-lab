"""Read-only reference artifacts, kept outside the single-satellite solver contract."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any


class ReferenceArchive:
    """Serve a pinned, integrity-checked EOS-Bench snapshot without solving it."""

    def __init__(self, path: Path) -> None:
        self.data: dict[str, Any] | None = None
        if path.is_file():
            raw = path.read_bytes()
            checksum = path.with_suffix(".sha256")
            if (
                not checksum.is_file()
                or hashlib.sha256(raw).hexdigest() != checksum.read_text().strip()
            ):
                raise ValueError("reference archive integrity check failed")
            data = json.loads(raw)
            if data.get("schema_version") != "eos-reference-1":
                raise ValueError("unsupported reference archive schema")
            self.data = data

    def catalog(self) -> dict[str, Any]:
        if self.data is None:
            return {"scenarios": [], "plans": []}
        scenario = self.data["scenario"]
        return {
            "scenarios": [
                {
                    "scenario_id": scenario["scenario_id"],
                    "name": scenario["name"],
                    "task_count": len(scenario["tasks"]),
                    "satellite_count": len(scenario["satellites"]),
                    "horizon_start_s": scenario["horizon_start_s"],
                    "horizon_end_s": scenario["horizon_end_s"],
                    "mode": "reference",
                    "geometry_note": (
                        "EOS-Bench source orbits and visibility windows; "
                        "simulation benchmark, not telemetry."
                    ),
                }
            ],
            "plans": [
                {
                    "solver_name": plan["plan_id"],
                    "label": plan["label"],
                    "category": "reference",
                    "stochastic": False,
                    "max_tasks": None,
                }
                for plan in self.data["plans"]
            ],
            "provenance": self.data["provenance"],
        }

    def payload(self, plan_id: str) -> dict[str, Any]:
        if self.data is None:
            raise ValueError("reference archive is unavailable")
        plan = next((p for p in self.data["plans"] if p["plan_id"] == plan_id), None)
        if plan is None:
            raise ValueError("unknown reference plan")
        scenario = self.data["scenario"]
        metrics = plan["recomputed_metrics"]
        return {
            "mode": "reference",
            "scenario": scenario,
            "replay": self.data["replay"],
            "provenance": self.data["provenance"],
            "reference_plan": plan,
            "result": {
                "schedule": {
                    "scenario_id": scenario["scenario_id"],
                    "solver_name": plan_id,
                    "seed": None,
                    "tasks": plan["assignments"],
                    "metadata": {
                        "stop_reason": "imported_reference",
                        "objective": plan["objective"],
                    },
                },
                "validation": {
                    "is_feasible": None,
                    "reference_consistent": not plan["checks"]["issues"],
                    "scope": (
                        "identity, intervals, source windows, satellite overlaps "
                        "and metric reconciliation only"
                    ),
                    "issues": plan["checks"]["issues"],
                    "simulation": {"tasks": plan["assignments"]},
                },
                "metrics": {
                    "total_value": metrics["TP"],
                    "completed_tasks": len(plan["assignments"]),
                    "total_slew_time_s": None,
                },
                "runtime_s": plan["source_metrics"]["RT"],
            },
            "evaluation": {**metrics, "RT": plan["source_metrics"]["RT"]},
            "convergence": [],
            "run_metadata": {
                "seed": "not recorded",
                "evaluation_budget": "not recorded",
                "evaluations": None,
                "stop_reason": "imported_reference",
                "source_revision": self.data["provenance"]["revision"],
                "software_version": "EOS-Bench source snapshot",
                "budget_profile": "source not recorded",
            },
        }

    def export(self) -> dict[str, Any] | None:
        """Copy data for a static build; no run is recomputed or re-labelled."""
        return deepcopy(self.data)
