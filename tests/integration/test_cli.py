import json
from pathlib import Path
from typing import Any

import orbitops.cli as cli_module
from orbitops.cli import app
from typer.testing import CliRunner

PROJECT_ROOT = Path(__file__).parents[2]
SCENARIO_PATH = PROJECT_ROOT / "scenarios" / "examples" / "demo.json"
SCHEDULE_PATH = PROJECT_ROOT / "scenarios" / "examples" / "feasible-schedule.json"
runner = CliRunner()


def test_lab_command_launches_configured_local_server(monkeypatch: Any) -> None:
    called: dict[str, object] = {}

    def fake_serve(scenario_dir: Path, *, host: str, port: int) -> None:
        called.update(scenario_dir=scenario_dir, host=host, port=port)

    monkeypatch.setattr(cli_module, "serve_lab", fake_serve)

    result = runner.invoke(
        app,
        [
            "lab",
            "--scenarios",
            str(PROJECT_ROOT / "scenarios"),
            "--host",
            "127.0.0.2",
            "--port",
            "8123",
        ],
    )

    assert result.exit_code == 0
    assert result.stdout == "OrbitOps Web Lab: http://127.0.0.2:8123\n"
    assert called == {
        "scenario_dir": PROJECT_ROOT / "scenarios",
        "host": "127.0.0.2",
        "port": 8123,
    }


def test_check_command_accepts_golden_schedule() -> None:
    result = runner.invoke(app, ["check", str(SCENARIO_PATH), str(SCHEDULE_PATH)])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["is_feasible"] is True
    assert payload["issues"] == []
    assert len(payload["simulation"]["tasks"]) == 3


def test_check_command_rejects_invalid_schedule(tmp_path: Path) -> None:
    schedule_payload = json.loads(SCHEDULE_PATH.read_text(encoding="utf-8"))
    schedule_payload["tasks"][0]["start_s"] = 1.0
    invalid_path = tmp_path / "invalid-schedule.json"
    invalid_path.write_text(json.dumps(schedule_payload), encoding="utf-8")

    result = runner.invoke(app, ["check", str(SCENARIO_PATH), str(invalid_path)])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["is_feasible"] is False
    assert {issue["code"] for issue in payload["issues"]} >= {
        "outside_window",
        "insufficient_slew_time",
    }


def test_solvers_command_lists_stable_names() -> None:
    result = runner.invoke(app, ["solvers"])

    assert result.exit_code == 0
    assert result.stdout.splitlines() == [
        "branch-and-bound",
        "brute-force",
        "genetic",
        "greedy-deadline",
        "greedy-density",
        "greedy-insertion",
        "greedy-value",
        "local-search",
        "random-feasible",
    ]


def test_solve_command_returns_validated_result() -> None:
    result = runner.invoke(
        app,
        ["solve", str(SCENARIO_PATH), "--solver", "greedy-insertion", "--seed", "42"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["schedule"]["solver_name"] == "greedy-insertion"
    assert payload["validation"]["is_feasible"] is True
    assert payload["metrics"]["total_value"] == 226.0


def test_solve_command_runs_exact_solver() -> None:
    scenario_path = PROJECT_ROOT / "scenarios" / "tiny" / "tiny-conflict.json"
    result = runner.invoke(app, ["solve", str(scenario_path), "--solver", "branch-and-bound"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["metrics"]["total_value"] == 18.0
    assert payload["schedule"]["metadata"]["optimality_proven"] is True


def test_solve_command_applies_search_evaluation_budget() -> None:
    result = runner.invoke(
        app,
        [
            "solve",
            str(SCENARIO_PATH),
            "--solver",
            "genetic",
            "--seed",
            "42",
            "--evaluation-budget",
            "25",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["validation"]["is_feasible"] is True
    assert payload["schedule"]["metadata"]["evaluation_budget"] == 25
    assert payload["schedule"]["metadata"]["evaluations"] <= 25


def test_solve_command_can_write_result(tmp_path: Path) -> None:
    output_path = tmp_path / "runs" / "demo-result.json"
    result = runner.invoke(
        app,
        ["solve", str(SCENARIO_PATH), "--solver", "greedy-value", "-o", str(output_path)],
    )

    assert result.exit_code == 0
    assert result.stdout == f"Wrote {output_path}\n"
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["validation"]["is_feasible"] is True


def test_benchmark_command_exports_reproducible_artifacts(tmp_path: Path) -> None:
    config_path = tmp_path / "benchmark.toml"
    config_path.write_text(
        """
benchmark_id = "cli-smoke"
master_seed = 73
sizes = ["tiny"]
difficulties = ["easy"]
instances_per_cell = 1
solvers = ["greedy-insertion", "genetic"]
algorithm_seeds = [0]
evaluation_budget = 20
""".strip()
        + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "benchmark-output"

    result = runner.invoke(
        app,
        ["benchmark", str(config_path), "--output", str(output_dir)],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["scenario_count"] == 1
    assert payload["run_count"] == 2
    assert payload["failed_runs"] == 0
    assert len(payload["reproducibility_fingerprint"]) == 64
    assert (output_dir / "report.json").is_file()
    assert (output_dir / "report.html").is_file()
    assert (output_dir / "summary.csv").is_file()
    assert (output_dir / "manifest.json").is_file()

    custom_report = tmp_path / "custom-report.html"
    report_result = runner.invoke(
        app,
        [
            "report",
            str(output_dir / "report.json"),
            "--output",
            str(custom_report),
            "--scenario-id",
            "cli-smoke-tiny-easy-000",
            "--solver",
            "genetic",
            "--seed",
            "0",
        ],
    )
    assert report_result.exit_code == 0
    report_payload = json.loads(report_result.stdout)
    assert report_payload["metrics_verified"] is True
    assert report_payload["scenario_id"] == "cli-smoke-tiny-easy-000"
    assert custom_report.is_file()
