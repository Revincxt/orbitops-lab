from pathlib import Path

STATIC_DIR = Path(__file__).parents[2] / "packages" / "orbitops" / "web" / "static"


def test_web_lab_has_accessible_product_specific_structure() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    assert 'id="solve-form"' in html
    assert 'aria-live="polite"' in html
    assert 'id="timeline-chart"' in html
    assert 'id="resource-chart"' in html
    assert 'id="learning-chart"' in html
    assert 'id="mission-globe"' in html
    assert 'id="comparison-body"' in html
    assert 'id="unscheduled-list"' in html
    assert 'aria-label="Run provenance"' in html
    assert "Cesium.js" in html
    assert "CesiumJS · NASA GIBS" in html
    assert "cesium-config.js" in html
    assert "Constrained satellite scheduling laboratory" in html
    assert "Schedule the orbit" not in html
    assert 'src="./deployment-config.js?v=0.2.0"' in html
    assert 'src="./app.js?v=0.2.0"' in html
    assert 'href="./app.css?v=0.2.0"' in html
    assert 'href="./favicon.svg?v=0.2.0"' in html


def test_web_lab_script_uses_safe_dom_and_real_api_endpoints() -> None:
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert 'api("/api/scenarios")' in script
    assert 'api("/api/solvers")' in script
    assert 'api("/api/solve"' in script
    assert "createElementNS" in script
    assert "replaceChildren" in script
    assert "new Cesium.Viewer" in script
    assert "BlueMarble_ShadedRelief_Bathymetry" in script
    assert "NaturalEarthII" in script
    assert "WebMercatorTilingScheme" in script
    assert "GoogleMapsCompatible_Level8" in script
    assert "training_trace" in script
    assert "visibility_windows" in script
    assert "innerHTML" not in script
    assert script.count("https://") == 1
    assert "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/" in script
    assert 'fetch("http' not in script
    assert 'fetch("./pages-data.json")' in script
    assert 'deployment.mode === "static"' in script
    assert "renderComparison" in script
    assert "renderConstraintAudit" in script
    assert "circularLongitudeCenter" in script
    assert "BoundingSphere.fromPoints" in script
    assert 'if (solverName === "q-learning") return "hybrid"' in script
    assert 'if (solverName === "q-policy-only") return "pure policy"' in script
    assert "Episode schedule objective" in script
    assert "Realized exploratory episode schedule objective" in script
    assert "Policy objective" not in script
    assert "state.solvers.forEach" in script


def test_web_lab_styles_are_responsive_and_use_warm_lavender_palette() -> None:
    stylesheet = (STATIC_DIR / "app.css").read_text(encoding="utf-8")

    assert "--lavender:" in stylesheet
    assert "--peach:" in stylesheet
    assert "--canvas:" in stylesheet
    assert ".globe-card" in stylesheet
    assert ".window-bar" in stylesheet
    assert ".td-line" in stylesheet
    assert ".comparison-table" in stylesheet
    assert ".audit-grid" in stylesheet
    assert ".run-record" in stylesheet
    assert ".visual-pair > .visual-block" in stylesheet
    assert "min-width: 0" in stylesheet
    assert "@media (max-width: 640px)" in stylesheet
    assert ":focus-visible" in stylesheet


def test_github_pages_build_is_reproducible_and_uses_official_actions() -> None:
    project_root = STATIC_DIR.parents[3]
    builder = (project_root / "scripts" / "build_pages.py").read_text(encoding="utf-8")
    workflow = (project_root / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")

    assert "DEFAULT_SEED = 42" in builder
    assert "DEFAULT_EVALUATION_BUDGET = 250" in builder
    assert '"mode": "precomputed-reproducibility-artifact"' in builder
    assert "astral-sh/setup-uv@v9.0.0" in workflow
    assert "actions/configure-pages@v5" in workflow
    assert "actions/upload-pages-artifact@v4" in workflow
    assert "actions/deploy-pages@v4" in workflow
