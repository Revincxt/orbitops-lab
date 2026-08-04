import json
from pathlib import Path

from orbitops.cli import app
from typer.testing import CliRunner

PROJECT_ROOT = Path(__file__).parents[2]
SCENARIO_PATH = PROJECT_ROOT / "scenarios" / "examples" / "demo.json"
SCHEDULE_PATH = PROJECT_ROOT / "scenarios" / "examples" / "feasible-schedule.json"
runner = CliRunner()


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
