"""Build the API-backed Web Lab as a static GitHub Pages artifact."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from orbitops import __version__
from orbitops.domain.models import Scenario
from orbitops.domain.transitions import required_slew_time_s
from orbitops.web import LabApplication

PROJECT_ROOT = Path(__file__).parents[1]
SCENARIO_DIR = PROJECT_ROOT / "scenarios"
STATIC_DIR = PROJECT_ROOT / "packages" / "orbitops" / "web" / "static"
DEFAULT_SEED = 42
DEFAULT_EVALUATION_BUDGET = 250
STATIC_EXACT_TIME_LIMIT_S = 3.0
ARTIFACT_MARKER = ".orbitops-pages-artifact"
ARTIFACT_MARKER_CONTENT = "orbitops-pages-v0.2\n"

# The Pages artifact is an inspectable reference dataset, not the full benchmark.
# Large scenarios retain representative method families while using smaller
# stochastic budgets so a deployment remains bounded on GitHub-hosted runners.
LARGE_SCENARIO_SOLVERS = frozenset(
    {
        "greedy-insertion",
        "greedy-density",
        "random-feasible",
        "local-search",
        "genetic",
        "q-learning",
    }
)
STATIC_EXACT_LIMITS = {"brute-force": 8, "branch-and-bound": 12}


def decode(response: Any) -> dict[str, Any]:
    if response.status != 200:
        raise RuntimeError(response.body.decode("utf-8"))
    return json.loads(response.body)


def _source_revision() -> str:
    revision = os.environ.get("GITHUB_SHA", "").strip()
    if revision:
        return revision

    head = PROJECT_ROOT / ".git" / "HEAD"
    try:
        value = head.read_text(encoding="utf-8").strip()
        if value.startswith("ref: "):
            reference = PROJECT_ROOT / ".git" / value.removeprefix("ref: ")
            value = reference.read_text(encoding="utf-8").strip()
        return value or "unavailable"
    except OSError:
        return "unavailable"


def _evaluation_budget(task_count: int, stochastic: bool) -> int:
    if not stochastic:
        return DEFAULT_EVALUATION_BUDGET
    if task_count >= 30:
        return 40
    if task_count >= 18:
        return 75
    if task_count >= 10:
        return 120
    return DEFAULT_EVALUATION_BUDGET


def _omission_reason(scenario: dict[str, Any], solver: dict[str, Any]) -> dict[str, str] | None:
    task_count = int(scenario["task_count"])
    solver_name = str(solver["solver_name"])
    max_tasks = solver["max_tasks"]
    if max_tasks is not None and task_count > int(max_tasks):
        return {
            "code": "solver_capability_limit",
            "reason": f"Method supports at most {max_tasks} tasks.",
        }
    static_limit = STATIC_EXACT_LIMITS.get(solver_name)
    if static_limit is not None and task_count > static_limit:
        return {
            "code": "pages_exact_profile_limit",
            "reason": (
                f"Exact search is omitted above {static_limit} tasks in the bounded Pages "
                "profile; run it locally with an explicit time limit."
            ),
        }
    if task_count >= 18 and solver_name not in LARGE_SCENARIO_SOLVERS:
        if solver_name == "q-policy-only":
            return {
                "code": "pages_large_policy_ablation_limit",
                "reason": (
                    "Pure-policy replay is omitted from the bounded large-scenario artifact; "
                    "the hybrid remains available here and both variants remain available locally."
                ),
            }
        return {
            "code": "pages_representative_method_set",
            "reason": "Omitted from the large-scenario Pages profile; available in the local lab.",
        }
    return None


def _has_temporal_attitude_slot(scenario: Scenario, run: dict[str, Any], task_id: str) -> bool:
    task_by_id = {task.task_id: task for task in scenario.tasks}
    task = task_by_id[task_id]
    simulation = run["result"]["validation"].get("simulation")
    scheduled = sorted((simulation or {}).get("tasks", []), key=lambda item: item["start_s"])
    satellite = scenario.satellite

    for window in task.visibility_windows:
        for position in range(len(scheduled) + 1):
            previous = scheduled[position - 1] if position else None
            following = scheduled[position] if position < len(scheduled) else None
            if previous is None:
                previous_end = scenario.horizon_start_s
                previous_attitude = satellite.initial_attitude_deg
            else:
                previous_end = float(previous["end_s"])
                previous_attitude = task_by_id[str(previous["task_id"])].required_attitude_deg

            earliest = max(
                window.start_s,
                previous_end
                + required_slew_time_s(satellite, previous_attitude, task.required_attitude_deg),
            )
            latest = window.end_s - task.duration_s
            if following is not None:
                following_task = task_by_id[str(following["task_id"])]
                latest = min(
                    latest,
                    float(following["start_s"])
                    - task.duration_s
                    - required_slew_time_s(
                        satellite,
                        task.required_attitude_deg,
                        following_task.required_attitude_deg,
                    ),
                )
            if earliest <= latest + 1e-9:
                return True
    return False


def _constraint_audit(run: dict[str, Any]) -> dict[str, Any]:
    scenario = Scenario.model_validate(run["scenario"])
    result = run["result"]
    validation = result["validation"]
    simulation = validation.get("simulation")
    scheduled_ids = {str(item["task_id"]) for item in (simulation or {}).get("tasks", [])}
    metadata = result["schedule"].get("metadata", {})
    stop_reason = str(metadata.get("stop_reason", "method_completed"))
    final_storage = float(
        (simulation or {})
        .get("final_state", {})
        .get("storage_gb", scenario.satellite.initial_storage_gb)
    )
    storage_remaining = max(0.0, scenario.satellite.storage_capacity_gb - final_storage)
    trace = (simulation or {}).get("tasks", [])
    minimum_energy = min(
        [scenario.satellite.initial_energy_wh] + [float(item["energy_after_wh"]) for item in trace]
    )

    issue_by_task: dict[str, list[dict[str, Any]]] = {}
    for issue in validation.get("issues", []):
        issue_by_task.setdefault(str(issue.get("task_id", "")), []).append(issue)

    unscheduled: list[dict[str, Any]] = []
    for task in scenario.tasks:
        if task.task_id in scheduled_ids:
            continue
        task_issues = issue_by_task.get(task.task_id, [])
        if task_issues:
            code = "validation_issue"
            reason = "; ".join(str(issue["message"]) for issue in task_issues)
        elif task.storage_cost_gb > storage_remaining + 1e-9:
            code = "storage_headroom"
            reason = (
                f"Incumbent storage headroom is {storage_remaining:.2f} GB; "
                f"the task requires {task.storage_cost_gb:.2f} GB."
            )
        elif task.energy_cost_wh > scenario.satellite.energy_capacity_wh + 1e-9:
            code = "energy_capacity"
            reason = "Task energy demand exceeds the satellite battery capacity."
        elif not _has_temporal_attitude_slot(scenario, run, task.task_id):
            code = "temporal_attitude_conflict"
            reason = "No remaining visibility slot satisfies duration, overlap, and slew margins."
        else:
            code = "termination_or_joint_resources"
            reason = (
                "A temporal slot remains, but the task was not selected before "
                f"{stop_reason.replace('_', ' ')}; energy and joint constraints may also bind."
            )
        unscheduled.append(
            {
                "task_id": task.task_id,
                "target_name": task.target.name,
                "reason_code": code,
                "reason": reason,
            }
        )

    return {
        "methodology": (
            "Incumbent-state diagnostic. Reasons describe insertion conditions around the final "
            "schedule and are not counterfactual causal proofs."
        ),
        "summary": {
            "scheduled_tasks": len(scheduled_ids),
            "unscheduled_tasks": len(unscheduled),
            "validation_issues": len(validation.get("issues", [])),
            "minimum_energy_wh": minimum_energy,
            "storage_remaining_gb": storage_remaining,
        },
        "issues": validation.get("issues", []),
        "unscheduled": unscheduled,
    }


def _run_metadata(
    result: dict[str, Any],
    *,
    solver: dict[str, Any],
    seed: int,
    evaluation_budget: int,
    source_revision: str,
    time_limit_s: float | None,
) -> dict[str, Any]:
    schedule_metadata = result["result"]["schedule"].get("metadata", {})
    if "stop_reason" in schedule_metadata:
        stop_reason = schedule_metadata["stop_reason"]
    elif schedule_metadata.get("timed_out"):
        stop_reason = "time_limit"
    elif schedule_metadata.get("optimality_proven"):
        stop_reason = "optimality_proven"
    else:
        stop_reason = "method_completed"
    evaluations = schedule_metadata.get("evaluations")
    if evaluations is None:
        evaluations = schedule_metadata.get("nodes_expanded")
    return {
        "solver_name": solver["solver_name"],
        "category": solver["category"],
        "stochastic": solver["stochastic"],
        "seed": seed,
        "evaluation_budget": evaluation_budget,
        "evaluations": evaluations,
        "stop_reason": stop_reason,
        "source_revision": source_revision,
        "software_version": __version__,
        "budget_profile": (
            "default" if evaluation_budget == DEFAULT_EVALUATION_BUDGET else "reduced-pages"
        ),
        "time_limit_s": time_limit_s,
    }


def build_dataset(application: LabApplication) -> dict[str, Any]:
    scenarios = decode(application.dispatch("GET", "/api/scenarios"))
    solvers = decode(application.dispatch("GET", "/api/solvers"))
    runs: dict[str, Any] = {}
    omissions: dict[str, Any] = {}
    source_revision = _source_revision()

    for scenario in scenarios["scenarios"]:
        for solver in solvers["solvers"]:
            key = f"{scenario['scenario_id']}::{solver['solver_name']}"
            omission = _omission_reason(scenario, solver)
            if omission is not None:
                omissions[key] = {
                    "scenario_id": scenario["scenario_id"],
                    "solver_name": solver["solver_name"],
                    **omission,
                }
                continue
            evaluation_budget = _evaluation_budget(
                int(scenario["task_count"]), bool(solver["stochastic"])
            )
            time_limit_s = STATIC_EXACT_TIME_LIMIT_S if solver["category"] == "exact" else None
            request_payload: dict[str, Any] = {
                "scenario_id": scenario["scenario_id"],
                "solver_name": solver["solver_name"],
                "seed": DEFAULT_SEED,
                "evaluation_budget": evaluation_budget,
            }
            if time_limit_s is not None:
                request_payload["time_limit_s"] = time_limit_s
            request = json.dumps(request_payload).encode()
            result = decode(application.dispatch("POST", "/api/solve", request))
            result["run_metadata"] = _run_metadata(
                result,
                solver=solver,
                seed=DEFAULT_SEED,
                evaluation_budget=evaluation_budget,
                source_revision=source_revision,
                time_limit_s=time_limit_s,
            )
            result["constraint_audit"] = _constraint_audit(result)
            runs[key] = result

    return {
        "metadata": {
            "mode": "precomputed-reproducibility-artifact",
            "schema_version": "0.2",
            "seed": DEFAULT_SEED,
            "evaluation_budget": DEFAULT_EVALUATION_BUDGET,
            "source_revision": source_revision,
            "software_version": __version__,
            "budget_policy": {
                "default": DEFAULT_EVALUATION_BUDGET,
                "task_count_10_to_17": 120,
                "task_count_18_to_29": 75,
                "task_count_30_plus": 40,
                "applies_to": "stochastic methods only",
            },
        },
        "scenarios": scenarios,
        "solvers": solvers,
        "runs": runs,
        "omissions": omissions,
        "reference": application.reference.export(),
    }


def _validate_output_target(output: Path) -> None:
    protected = (PROJECT_ROOT.resolve(), STATIC_DIR.resolve(), SCENARIO_DIR.resolve())
    if output == protected[0] or output in protected[0].parents:
        raise ValueError("output directory must not replace the project or one of its parents")
    if any(output == path or output.is_relative_to(path) for path in protected[1:]):
        raise ValueError("output directory must not be inside project source assets")
    if output.exists() and not output.is_dir():
        raise ValueError("output path exists and is not a directory")
    if output.exists() and any(output.iterdir()):
        marker = output / ARTIFACT_MARKER
        try:
            marker_content = marker.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(
                "refusing to replace a non-empty directory without the OrbitOps artifact marker"
            ) from exc
        if marker_content != ARTIFACT_MARKER_CONTENT:
            raise ValueError("refusing to replace a directory with an invalid artifact marker")


def build_pages(output_dir: Path) -> None:
    output = output_dir.resolve()
    _validate_output_target(output)
    dataset = build_dataset(LabApplication(SCENARIO_DIR))
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f".{output.name}-", dir=output.parent) as temporary:
        staging = Path(temporary) / "artifact"
        shutil.copytree(STATIC_DIR, staging)
        deployment_config = (
            '"use strict";\n\nwindow.ORBITOPS_DEPLOYMENT = Object.freeze({ mode: "static" });\n'
        )
        (staging / "deployment-config.js").write_text(deployment_config, encoding="utf-8")
        (staging / "pages-data.json").write_text(
            json.dumps(dataset, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        (staging / ARTIFACT_MARKER).write_text(ARTIFACT_MARKER_CONTENT, encoding="utf-8")
        (staging / ".nojekyll").touch()

        previous = Path(temporary) / "previous"
        if output.exists():
            output.replace(previous)
        try:
            staging.replace(output)
        except OSError:
            if previous.exists() and not output.exists():
                previous.replace(output)
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "site")
    args = parser.parse_args()
    build_pages(args.output)


if __name__ == "__main__":
    main()
