import json
from pathlib import Path

from orbitops.web import LabApplication
from orbitops.web.app import MAX_REQUEST_BYTES

from tests.factories import make_seeded_scenario

PROJECT_ROOT = Path(__file__).parents[2]
SCENARIO_DIR = PROJECT_ROOT / "scenarios"


def payload(response: object) -> dict[str, object]:
    return json.loads(response.body)  # type: ignore[attr-defined, no-any-return]


def solve_body(**overrides: object) -> bytes:
    request = {
        "scenario_id": "demo-001",
        "solver_name": "greedy-insertion",
        "seed": 42,
        "evaluation_budget": 25,
    }
    request.update(overrides)
    return json.dumps(request).encode()


def test_catalog_exposes_only_valid_scenarios_and_solver_capabilities() -> None:
    application = LabApplication(SCENARIO_DIR)

    health = application.dispatch("GET", "/api/health")
    scenarios = application.dispatch("GET", "/api/scenarios?cache=no")
    solvers = application.dispatch("GET", "/api/solvers")

    assert health.status == 200
    assert payload(health)["scenario_count"] == 7
    scenario_items = payload(scenarios)["scenarios"]
    assert {item["scenario_id"] for item in scenario_items} == {  # type: ignore[index, union-attr]
        "demo-001",
        "showcase-global-30",
        "showcase-resources-10",
        "showcase-slew-18",
        "showcase-temporal-06",
        "tiny-conflict",
        "tiny-resource",
    }
    global_summary = next(  # type: ignore[arg-type]
        item for item in scenario_items if item["scenario_id"] == "showcase-global-30"
    )
    assert global_summary["research_question"].startswith("How do scalable heuristics")
    assert global_summary["geometry_note"].endswith("access windows are synthetic.")
    solver_items = payload(solvers)["solvers"]
    metadata = {item["solver_name"]: item for item in solver_items}  # type: ignore[index, union-attr]
    assert metadata["greedy-insertion"]["category"] == "baseline"
    assert metadata["brute-force"]["max_tasks"] == 10
    assert metadata["branch-and-bound"]["max_tasks"] == 16
    assert metadata["genetic"]["stochastic"] is True
    assert metadata["q-learning"]["category"] == "advanced"
    assert metadata["q-learning"]["stochastic"] is True
    assert metadata["q-policy-only"]["category"] == "advanced"
    assert metadata["q-policy-only"]["stochastic"] is True


def test_solve_returns_validated_schedule_and_visualization_data() -> None:
    application = LabApplication(SCENARIO_DIR)

    response = application.dispatch("POST", "/api/solve", solve_body())

    assert response.status == 200
    data = payload(response)
    result = data["result"]
    assert result["schedule"]["solver_name"] == "greedy-insertion"  # type: ignore[index]
    assert result["validation"]["is_feasible"] is True  # type: ignore[index]
    assert result["metrics"]["total_value"] == 226.0  # type: ignore[index]
    assert len(result["validation"]["simulation"]["tasks"]) == 3  # type: ignore[index]
    assert data["convergence"]


def test_search_solve_honors_budget_and_publishes_convergence() -> None:
    application = LabApplication(SCENARIO_DIR)

    response = application.dispatch(
        "POST",
        "/api/solve",
        solve_body(solver_name="genetic", evaluation_budget=20),
    )

    assert response.status == 200
    data = payload(response)
    schedule = data["result"]["schedule"]  # type: ignore[index]
    assert schedule["metadata"]["evaluation_budget"] == 20
    assert schedule["metadata"]["evaluations"] <= 20
    assert data["convergence"] == schedule["metadata"]["convergence"]


def test_solve_rejects_bad_payloads_and_unknown_inputs() -> None:
    application = LabApplication(SCENARIO_DIR)

    malformed = application.dispatch("POST", "/api/solve", b"not-json")
    unknown_scenario = application.dispatch("POST", "/api/solve", solve_body(scenario_id="missing"))
    unknown_solver = application.dispatch("POST", "/api/solve", solve_body(solver_name="magic"))
    oversized = application.dispatch("POST", "/api/solve", b"x" * (MAX_REQUEST_BYTES + 1))

    assert malformed.status == 422
    assert payload(malformed)["details"]
    assert unknown_scenario.status == 400
    assert "unknown scenario" in payload(unknown_scenario)["error"]  # type: ignore[operator]
    assert unknown_solver.status == 400
    assert "unknown solver" in payload(unknown_solver)["error"]  # type: ignore[operator]
    assert oversized.status == 413


def test_exact_solver_limit_is_reported_without_running_search(tmp_path: Path) -> None:
    scenario = make_seeded_scenario(99, task_count=17)
    scenario.to_json(tmp_path / "large.json")
    application = LabApplication(tmp_path)

    response = application.dispatch(
        "POST",
        "/api/solve",
        solve_body(scenario_id=scenario.scenario_id, solver_name="branch-and-bound"),
    )

    assert response.status == 400
    assert "supports at most 16 tasks" in payload(response)["error"]  # type: ignore[operator]


def test_static_and_scenario_routes_are_fixed_and_safe(tmp_path: Path) -> None:
    application = LabApplication(SCENARIO_DIR)

    homepage = application.dispatch("GET", "/")
    stylesheet = application.dispatch("GET", "/app.css")
    script = application.dispatch("GET", "/app.js")
    orbit_model = application.dispatch("GET", "/orbit-model.js")
    sensor_fov = application.dispatch("GET", "/sensor-fov.js")
    cesium_config = application.dispatch("GET", "/cesium-config.js")
    deployment_config = application.dispatch("GET", "/deployment-config.js")
    social_card = application.dispatch("GET", "/orbitops-social-card.jpg")
    favicon = application.dispatch("GET", "/favicon.svg?v=0.2.0")
    font = application.dispatch("GET", "/fonts/InterVariable.woff2")
    font_license = application.dispatch("GET", "/fonts/OFL.txt")
    scenario = application.dispatch("GET", "/api/scenarios/demo-001")
    missing_scenario = application.dispatch("GET", "/api/scenarios/unknown")
    traversal = application.dispatch("GET", "/../pyproject.toml")
    wrong_method = application.dispatch("POST", "/")
    missing_asset = LabApplication(SCENARIO_DIR, static_dir=tmp_path).dispatch("GET", "/")

    assert (
        homepage.status
        == stylesheet.status
        == script.status
        == orbit_model.status
        == sensor_fov.status
        == cesium_config.status
        == deployment_config.status
        == social_card.status
        == favicon.status
        == font.status
        == font_license.status
        == 200
    )
    assert homepage.content_type.startswith("text/html")
    assert stylesheet.content_type.startswith("text/css")
    assert script.content_type.startswith("text/javascript")
    assert orbit_model.content_type.startswith("text/javascript")
    assert sensor_fov.content_type.startswith("text/javascript")
    assert cesium_config.content_type.startswith("text/javascript")
    assert deployment_config.content_type.startswith("text/javascript")
    assert social_card.content_type == "image/jpeg"
    assert favicon.content_type == "image/svg+xml"
    assert font.content_type == "font/woff2"
    assert font.body.startswith(b"wOF2")
    assert font_license.content_type.startswith("text/plain")
    assert b"SIL OPEN FONT LICENSE" in font_license.body
    assert application.dispatch("GET", "/fonts/../app.py").status == 404
    assert payload(scenario)["scenario_id"] == "demo-001"
    assert missing_scenario.status == traversal.status == wrong_method.status == 404
    assert missing_asset.status == 404


def test_application_rejects_invalid_catalogs(tmp_path: Path) -> None:
    (tmp_path / "not-a-scenario.json").write_text('{"hello": "world"}', encoding="utf-8")

    try:
        LabApplication(tmp_path)
    except ValueError as exc:
        assert "no valid scenarios" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("invalid catalog was accepted")

    missing = tmp_path / "missing"
    try:
        LabApplication(missing)
    except ValueError as exc:
        assert "does not exist" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("missing catalog was accepted")


def test_application_rejects_duplicate_scenario_ids(tmp_path: Path) -> None:
    scenario = make_seeded_scenario(3, task_count=2)
    scenario.to_json(tmp_path / "one.json")
    scenario.to_json(tmp_path / "two.json")

    try:
        LabApplication(tmp_path)
    except ValueError as exc:
        assert "duplicate scenario_id" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("duplicate scenario IDs were accepted")
