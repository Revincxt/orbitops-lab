import json
from pathlib import Path

import pytest
from orbitops import Scenario
from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).parents[2]
DEMO_PATH = PROJECT_ROOT / "scenarios" / "examples" / "demo.json"
SCHEMA_PATH = PROJECT_ROOT / "schemas" / "scenario-v0.1.schema.json"


def test_demo_scenario_loads() -> None:
    scenario = Scenario.from_json(DEMO_PATH)

    assert scenario.schema_version == "0.1"
    assert scenario.scenario_id == "demo-001"
    assert len(scenario.tasks) == 3
    assert scenario.tasks[0].visibility_windows[0].duration_s == 190.0


def test_committed_json_schema_matches_runtime_model() -> None:
    committed_schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert committed_schema == Scenario.model_json_schema()


def test_unknown_fields_are_rejected() -> None:
    payload = Scenario.from_json(DEMO_PATH).model_dump(mode="json")
    payload["surprise"] = True

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Scenario.model_validate(payload)


def test_duplicate_task_ids_are_rejected() -> None:
    payload = Scenario.from_json(DEMO_PATH).model_dump(mode="json")
    payload["tasks"][1]["task_id"] = payload["tasks"][0]["task_id"]

    with pytest.raises(ValidationError, match="task_id values must be unique"):
        Scenario.model_validate(payload)


def test_window_must_stay_inside_horizon() -> None:
    payload = Scenario.from_json(DEMO_PATH).model_dump(mode="json")
    payload["tasks"][0]["visibility_windows"][0]["end_s"] = 2000.0

    with pytest.raises(ValidationError, match="must lie inside the scenario horizon"):
        Scenario.model_validate(payload)


def test_task_must_fit_at_least_one_window() -> None:
    payload = Scenario.from_json(DEMO_PATH).model_dump(mode="json")
    payload["tasks"][0]["duration_s"] = 500.0

    with pytest.raises(ValidationError, match="must fit in at least one"):
        Scenario.model_validate(payload)
