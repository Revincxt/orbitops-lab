"""Build the API-backed Web Lab as a static GitHub Pages artifact."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from orbitops.web import LabApplication

PROJECT_ROOT = Path(__file__).parents[1]
SCENARIO_DIR = PROJECT_ROOT / "scenarios"
STATIC_DIR = PROJECT_ROOT / "packages" / "orbitops" / "web" / "static"
DEFAULT_SEED = 42
DEFAULT_EVALUATION_BUDGET = 250


def decode(response: Any) -> dict[str, Any]:
    if response.status != 200:
        raise RuntimeError(response.body.decode("utf-8"))
    return json.loads(response.body)


def build_dataset(application: LabApplication) -> dict[str, Any]:
    scenarios = decode(application.dispatch("GET", "/api/scenarios"))
    solvers = decode(application.dispatch("GET", "/api/solvers"))
    runs: dict[str, Any] = {}

    for scenario in scenarios["scenarios"]:
        for solver in solvers["solvers"]:
            max_tasks = solver["max_tasks"]
            if max_tasks is not None and scenario["task_count"] > max_tasks:
                continue
            request = json.dumps(
                {
                    "scenario_id": scenario["scenario_id"],
                    "solver_name": solver["solver_name"],
                    "seed": DEFAULT_SEED,
                    "evaluation_budget": DEFAULT_EVALUATION_BUDGET,
                }
            ).encode()
            result = decode(application.dispatch("POST", "/api/solve", request))
            runs[f"{scenario['scenario_id']}::{solver['solver_name']}"] = result

    return {
        "metadata": {
            "mode": "precomputed-reproducibility-artifact",
            "seed": DEFAULT_SEED,
            "evaluation_budget": DEFAULT_EVALUATION_BUDGET,
        },
        "scenarios": scenarios,
        "solvers": solvers,
        "runs": runs,
    }


def build_pages(output_dir: Path) -> None:
    output = output_dir.resolve()
    if output in {PROJECT_ROOT.resolve(), STATIC_DIR.resolve()}:
        raise ValueError("output directory must not replace project source")
    if output.exists():
        shutil.rmtree(output)
    shutil.copytree(STATIC_DIR, output)

    deployment_config = (
        '"use strict";\n\nwindow.ORBITOPS_DEPLOYMENT = Object.freeze({ mode: "static" });\n'
    )
    (output / "deployment-config.js").write_text(deployment_config, encoding="utf-8")
    dataset = build_dataset(LabApplication(SCENARIO_DIR))
    (output / "pages-data.json").write_text(
        json.dumps(dataset, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / ".nojekyll").touch()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "site")
    args = parser.parse_args()
    build_pages(args.output)


if __name__ == "__main__":
    main()
