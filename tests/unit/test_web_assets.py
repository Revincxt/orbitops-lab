from pathlib import Path

STATIC_DIR = Path(__file__).parents[2] / "packages" / "orbitops" / "web" / "static"


def test_web_lab_has_accessible_product_specific_structure() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    assert 'id="solve-form"' in html
    assert 'aria-live="polite"' in html
    assert 'id="timeline-chart"' in html
    assert 'id="resource-chart"' in html
    assert 'id="mission-globe"' in html
    assert 'aria-label="Map projection"' in html
    assert all(f'id="{view}"' in html for view in ["view-3d", "view-2_5d", "view-2d"])
    assert 'id="comparison-body"' in html
    assert "Cesium.js" in html
    assert 'id="toggle-layers"' in html
    assert 'aria-controls="layer-options"' in html
    assert "cesium-config.js" in html
    assert "EOS-Bench" in html
    assert all(
        f'id="{removed}"' not in html
        for removed in [
            "scenario-select",
            "seed-input",
            "budget-input",
            "scenario-context",
            "model-note",
            "mission-name",
            "mission-id",
            "mission-horizon",
            "deployment-mode",
            "replay-progress",
            "toggle-config",
            "toggle-inspector",
            "tab-audit",
            "pane-audit",
            "tab-learning",
            "pane-learning",
            "tab-provenance",
            "inspector-provenance",
            "metric-value",
            "metric-tasks",
            "metric-slew",
            "metric-feasible",
            "camera-focus",
        ]
    )
    assert "Schedule the orbit" not in html
    assert 'src="./deployment-config.js?v=0.2.0"' in html
    assert 'src="./app.js?v=0.7.0"' in html
    assert 'src="./replay.js?v=0.7.0"' in html
    assert 'src="./mission.js?v=0.7.0"' in html
    assert 'href="./app.css?v=0.7.0"' in html
    assert 'href="./favicon.svg?v=0.2.0"' in html


def test_web_lab_script_uses_safe_dom_and_real_api_endpoints() -> None:
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert 'api("/api/reference/data")' in script
    assert 'api("/api/scenarios")' not in script
    assert 'api("/api/solvers")' not in script
    assert 'api("/api/solve"' not in script
    assert "createElementNS" in script
    assert "replaceChildren" in script
    assert "new Cesium.Viewer" in script
    assert "scene3DOnly: false" in script
    assert "Cesium.MapMode2D.ROTATE" in script
    assert "BlueMarble_ShadedRelief/default" in script
    assert "NaturalEarthII" in script
    assert "WebMercatorTilingScheme" in script
    assert "GoogleMapsCompatible_Level8" in script
    assert "visibility_windows" in script
    assert "innerHTML" not in script
    assert script.count("https://") == 1
    assert "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/" in script
    assert 'fetch("http' not in script
    assert 'fetch("./pages-data.json")' in script
    assert 'deployment.mode === "static"' in script
    assert "renderComparison" in script
    assert "renderConstraintAudit" not in script
    assert "setPanel(" not in script
    assert "setWorkspaceView" in script
    assert "sequence-local" not in script
    assert "q-learning" not in script
    assert "setLayersOpen" in script
    assert "referencePayload" in script


def test_satellite_camera_supports_double_click_focus_without_a_focus_button() -> None:
    mission = (STATIC_DIR / "mission.js").read_text(encoding="utf-8")
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "focusSelectedSatellite" in mission
    assert '"camera-focus"' not in mission
    assert 'cameraMode = "focus"' not in mission + script
    assert "inspect(event.position, true), Cesium.ScreenSpaceEventType.LEFT_DOUBLE_CLICK" in mission
    assert "removeInputAction(Cesium.ScreenSpaceEventType.LEFT_DOUBLE_CLICK)" not in mission
    assert "followSelectedSatellite" in mission


def test_web_lab_styles_use_a_fixed_viewport_engineering_workspace() -> None:
    stylesheet = (STATIC_DIR / "app.css").read_text(encoding="utf-8")

    assert "color-scheme: dark" in stylesheet
    assert "--accent:" in stylesheet
    assert "--canvas:" in stylesheet
    assert ".globe-card" in stylesheet
    assert ".window-bar" in stylesheet
    assert ".td-line" in stylesheet
    assert ".comparison-table" in stylesheet
    assert ".audit-grid" not in stylesheet
    assert ".metric-grid" not in stylesheet
    assert ".metric-details" in stylesheet
    assert ".center-workspace" in stylesheet
    assert ".analysis-dock" in stylesheet
    assert "height: 100dvh" in stylesheet
    assert "overscroll-behavior: none" in stylesheet
    assert "overflow-y: auto" not in stylesheet
    assert "overflow-x: auto" not in stylesheet
    assert "min-width: 0" in stylesheet
    assert "@media (max-width: 640px)" in stylesheet
    assert ":focus-visible" in stylesheet


def test_github_pages_build_is_reproducible_and_uses_official_actions() -> None:
    project_root = STATIC_DIR.parents[3]
    builder = (project_root / "scripts" / "build_pages.py").read_text(encoding="utf-8")
    workflow = (project_root / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")

    assert 'dispatch("POST", "/api/solve"' not in builder
    assert '"mode": "eos-bench-reference-replay"' in builder
    assert "astral-sh/setup-uv@v9.0.0" in workflow
    assert "actions/configure-pages@v5" in workflow
    assert "actions/upload-pages-artifact@v4" in workflow
    assert "actions/deploy-pages@v4" in workflow
