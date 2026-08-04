from pathlib import Path

STATIC_DIR = Path(__file__).parents[2] / "packages" / "orbitops" / "web" / "static"


def test_web_lab_has_accessible_product_specific_structure() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    assert 'id="solve-form"' in html
    assert 'aria-live="polite"' in html
    assert 'id="timeline-chart"' in html
    assert 'id="resource-chart"' in html
    assert 'id="convergence-chart"' in html
    assert 'src="/app.js"' in html
    assert 'href="/app.css"' in html
    assert "https://" not in html


def test_web_lab_script_uses_safe_dom_and_real_api_endpoints() -> None:
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert 'api("/api/scenarios")' in script
    assert 'api("/api/solvers")' in script
    assert 'api("/api/solve"' in script
    assert "createElementNS" in script
    assert "replaceChildren" in script
    assert "innerHTML" not in script
    assert "https://" not in script
    assert 'fetch("http' not in script


def test_web_lab_styles_are_responsive_and_use_warm_lavender_palette() -> None:
    stylesheet = (STATIC_DIR / "app.css").read_text(encoding="utf-8")

    assert "--lavender:" in stylesheet
    assert "--peach:" in stylesheet
    assert "--canvas:" in stylesheet
    assert "@media (max-width: 640px)" in stylesheet
    assert ":focus-visible" in stylesheet
