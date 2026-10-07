import json
from pathlib import Path

import pytest
from orbitops.web import LabApplication

PROJECT_ROOT = Path(__file__).parents[2]
REFERENCE_PATH = PROJECT_ROOT / "data/eos-bench/reference.json"


def payload(response: object) -> dict[str, object]:
    return json.loads(response.body)  # type: ignore[attr-defined, no-any-return]


def test_health_and_reference_expose_only_the_eos_bench_scene() -> None:
    application = LabApplication(REFERENCE_PATH)
    health = application.dispatch("GET", "/api/health?cache=no")
    assert health.status == 200
    assert payload(health) == {
        "status": "ok",
        "mode": "eos-bench-reference-replay",
        "scenario_count": 1,
    }
    response = application.dispatch("GET", "/api/reference/data")
    assert response.status == 200
    data = json.loads(response.body)
    assert data["scenario"]["scenario_id"] == "eos-s1-20-500"
    assert len(data["scenario"]["satellites"]) == 20
    assert len(data["scenario"]["tasks"]) == 500
    assert len(data["plans"]) == 7


@pytest.mark.parametrize(
    "route",
    [
        "/api/scenarios",
        "/api/scenarios/demo-001",
        "/api/solvers",
        "/api/solve",
        "/api/reference",
        "/api/reference/runs/eos-sa-balanced",
        "/api/reference/runs/not-found",
        "/orbitops-social-card.jpg",
    ],
)
def test_retired_routes_are_not_exposed(route: str) -> None:
    assert LabApplication(REFERENCE_PATH).dispatch("GET", route).status == 404


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_service_refuses_writes_without_entering_the_solver(
    method: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_solver(*args: object, **kwargs: object) -> None:
        raise AssertionError("Replay service must never construct a solver")

    monkeypatch.setattr("orbitops.solvers.registry.get_solver", forbidden_solver)
    app = LabApplication(REFERENCE_PATH)
    for route in ["/", "/api/solve", "/api/reference/data"]:
        response = app.dispatch(method, route)
        assert response.status == 405
        assert "read-only" in str(payload(response)["error"])


@pytest.mark.parametrize(
    "route, content_type",
    [
        ("/", "text/html; charset=utf-8"),
        ("/app.css", "text/css; charset=utf-8"),
        ("/app.js", "text/javascript; charset=utf-8"),
        ("/replay.js", "text/javascript; charset=utf-8"),
        ("/orbit-model.js", "text/javascript; charset=utf-8"),
        ("/orbit-ephemeris.js", "text/javascript; charset=utf-8"),
        ("/satellite-attitude.js", "text/javascript; charset=utf-8"),
        ("/sensor-fov.js", "text/javascript; charset=utf-8"),
        ("/mission.js", "text/javascript; charset=utf-8"),
        ("/cesium-config.js", "text/javascript; charset=utf-8"),
        ("/deployment-config.js", "text/javascript; charset=utf-8"),
        ("/models/earth-observer.glb", "model/gltf-binary"),
        ("/favicon.svg", "image/svg+xml"),
        ("/fonts/InterVariable.woff2", "font/woff2"),
        ("/fonts/OFL.txt", "text/plain; charset=utf-8"),
    ],
)
def test_current_static_routes_remain_available(route: str, content_type: str) -> None:
    response = LabApplication(REFERENCE_PATH).dispatch("GET", route + "?v=current")
    assert response.status == 200
    assert response.content_type == content_type
    assert response.body
    if route.endswith(".glb"):
        assert response.body.startswith(b"glTF")
    if route.endswith(".woff2"):
        assert response.body.startswith(b"wOF2")
    if route.endswith("OFL.txt"):
        assert b"SIL OPEN FONT LICENSE" in response.body


@pytest.mark.parametrize(
    "route",
    [
        "/../pyproject.toml",
        "/%2e%2e/pyproject.toml",
        "/models/../app.js",
        "/fonts/../app.py",
        "/reference.json",
        "/api/scenarios/../reference.json",
    ],
)
def test_arbitrary_files_are_not_served(route: str) -> None:
    assert LabApplication(REFERENCE_PATH).dispatch("GET", route).status == 404


def test_missing_archive_reports_unavailable_but_can_serve_the_shell(tmp_path: Path) -> None:
    app = LabApplication(tmp_path / "missing.json")
    assert app.dispatch("GET", "/").status == 200
    response = app.dispatch("GET", "/api/health")
    assert response.status == 503
    assert payload(response)["scenario_count"] == 0
    assert payload(response)["status"] == "unavailable"
    assert app.dispatch("GET", "/api/reference/data").status == 503
    assert app.dispatch("GET", "/orbit-data/00000.json").status == 404


def test_reference_startup_does_not_load_synthetic_scenarios(tmp_path: Path) -> None:
    archive = tmp_path / "reference.json"
    archive.write_bytes(REFERENCE_PATH.read_bytes())
    archive.with_suffix(".sha256").write_bytes(REFERENCE_PATH.with_suffix(".sha256").read_bytes())
    # No scenario directory is needed, even if adjacent unrelated JSON is invalid.
    (tmp_path / "not-a-scenario.json").write_text("invalid")
    assert LabApplication(archive).dispatch("GET", "/api/health").status == 200


def test_missing_static_asset_is_not_an_internal_error(tmp_path: Path) -> None:
    app = LabApplication(REFERENCE_PATH, static_dir=tmp_path)
    assert app.dispatch("GET", "/").status == 404
