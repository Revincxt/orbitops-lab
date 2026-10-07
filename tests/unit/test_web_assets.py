from pathlib import Path

STATIC_DIR = Path(__file__).parents[2] / "packages" / "orbitops" / "web" / "static"


def test_web_lab_has_accessible_product_specific_structure() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    assert 'class="algorithm-control"' in html
    assert 'aria-label="Optimization Algorithm"' in html
    assert ">Optimization Algorithm<" not in html
    assert 'for="solver-select"' not in html
    assert ">Task List<" in html
    assert 'aria-live="polite"' in html
    assert 'id="timeline-chart"' in html
    assert 'id="resource-chart"' in html
    assert 'id="mission-globe"' in html
    assert 'aria-label="Map projection"' in html
    assert all(f'id="{view}"' in html for view in ["view-3d", "view-2_5d", "view-2d"])
    assert 'id="comparison-chart"' in html
    assert 'id="comparison-legend"' in html
    assert 'id="comparison-values"' in html
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
            "export-run",
            "i-export",
            "orbit-span",
            "solve-form",
            "run-button",
            "run-label",
            "pending-state",
            "tab-comparison",
            "pane-comparison",
            "comparison-body",
            "target-next",
            "target-prev",
            "target-count",
            "target-search",
            "comparison-info",
            "comparison-scales",
            "timeline-title",
            "timeline-prev",
            "timeline-next",
            "timeline-range",
            "energy-readout",
            "storage-readout",
        ]
    )
    assert "Schedule the orbit" not in html
    assert "ACTIVE SATELLITES" not in html
    assert "OBSERVATION TIME" not in html
    assert 'src="./deployment-config.js?v=0.2.0"' in html
    for name in [
        "app",
        "replay",
        "orbit-model",
        "orbit-ephemeris",
        "satellite-attitude",
        "sensor-fov",
        "mission",
    ]:
        assert f'src="./{name}.js?v=0.26.0"' in html
    assert 'href="./app.css?v=0.21.0"' in html
    assert 'href="./favicon.svg?v=0.2.0"' in html
    assert 'id="sun-direction"' not in html
    assert 'class="app-title"' not in html
    assert 'class="header-divider"' not in html
    assert ">Mission workspace<" not in html
    assert 'class="visually-hidden">OrbitOps<' in html
    assert "MISSION CONTROL" not in html.upper()
    assert 'class="orbit-hud-footer"' not in html
    assert 'aria-label="Satellite details"' in html
    assert 'id="close-satellite-details"' in html
    assert 'aria-label="Earth-centered Earth-fixed position in kilometres"' in html
    assert all(f'id="satellite-position-{axis}"' in html for axis in "xyz")
    assert 'id="satellite-latitude"' in html
    assert 'id="satellite-longitude"' in html
    assert 'href="#i-overview"' in html
    assert 'href="#i-follow"' in html
    assert ">000°<" not in html
    assert 'id="camera-heading"' not in html
    assert 'class="orbit-legend"' not in html
    assert 'aria-label="Map actions"' in html
    assert html.count('class="map-action') == 5
    assert html.index('aria-labelledby="targets-title"') < html.index(
        'aria-labelledby="comparison-title"'
    )
    assert html.count("command-card console-panel") == 5
    assert 'class="globe-card command-card"' in html
    assert "Sensor FOV · 45°" in html
    assert "full cone angle 45°, half-angle 22.5°" in html
    assert 'id="toggle-rays"' not in html
    assert "Observation links" not in html


def test_compact_panel_headers_remove_search_markup_and_dependencies() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    stylesheet = (STATIC_DIR / "app.css").read_text(encoding="utf-8")
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    mission = (STATIC_DIR / "mission.js").read_text(encoding="utf-8")

    assert "target-search" not in html + script + mission
    assert "catalog-filters" not in html + stylesheet
    assert "Find task" not in html
    assert 'aria-label="Filter task status"' in html
    assert 'class="panel-heading inspector-heading"' in html
    assert 'role="tablist" aria-label="Inspector views"' in html
    assert 'role="tabpanel" aria-labelledby="tab-selection"' in html
    assert 'role="tabpanel" aria-labelledby="tab-evaluation"' in html


def test_web_lab_script_uses_safe_dom_and_real_api_endpoints() -> None:
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert 'fetch("/api/reference/data")' in script
    assert 'fetch("/api/scenarios")' not in script
    assert 'fetch("/api/solvers")' not in script
    assert 'fetch("/api/solve"' not in script
    assert "createElementNS" in script
    assert "replaceChildren" in script
    assert "new Cesium.Viewer" in script
    assert "scene3DOnly: false" in script
    assert "Cesium.MapMode2D.ROTATE" in script
    assert "state.globe.scene.skyBox.show = true" in script
    assert "state.globe.scene.skyBox.show = false" not in script
    assert "state.globe.scene.sun.show = true" in script
    assert "state.globe.scene.globe.enableLighting = true" in script
    assert "BlueMarble_ShadedRelief/default" in script
    assert "NaturalEarthII" in script
    assert "new Cesium.GridImageryProvider" in script
    assert "backgroundColor: Cesium.Color.TRANSPARENT" in script
    assert "WebMercatorTilingScheme" in script
    assert "GoogleMapsCompatible_Level8" in script
    assert "visibility_windows" in script
    assert "innerHTML" not in script
    assert "elements.export" not in script
    assert "createObjectURL" not in script
    assert "link.download" not in script
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
    assert 'elements.solver.addEventListener("change", loadReferencePlan)' in script
    assert "markConfigurationChanged" not in script


def test_information_controls_are_removed_without_deleting_map_credit_content() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    stylesheet = (STATIC_DIR / "app.css").read_text(encoding="utf-8")
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    for removed in ["comparison-info", "comparison-scales", "attribution-icon"]:
        assert removed not in html + stylesheet + script
    assert "setComparisonScalesOpen" not in script
    assert "styleMapAttribution" not in script
    assert "hideMapCreditToggle();" in script
    assert "link.hidden = true" in script
    assert "link.tabIndex = -1" in script
    assert "cesium-credit-logoContainer img" in stylesheet
    assert "credit: new Cesium.Credit" in script


def test_live_utc_clock_and_picker_are_in_the_brand_header() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    header = html.split('<header class="masthead">', 1)[1].split("</header>", 1)[0]

    assert 'class="brand-block"' in header
    for control in ["replay-time-button", "replay-time", "replay-time-picker", "replay-utc-input"]:
        assert html.count(f'id="{control}"') == 1
        assert f'id="{control}"' in header
    assert header.index('class="brand"') < header.index('id="replay-time-button"')
    assert 'aria-controls="replay-time-picker"' in header


def test_playback_controls_are_one_accessible_group() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert 'class="replay-controls" role="group" aria-label="Playback controls"' in html
    controls = html.split('class="replay-controls"', 1)[1].split("</div>", 1)[0]
    for control in [
        "replay-window-prev",
        "replay-play",
        "replay-window-next",
        "replay-reset",
        "replay-direction",
        "replay-speed",
    ]:
        assert f'id="{control}"' in controls
    assert controls.index('id="replay-play"') < controls.index('id="replay-window-next"')
    assert controls.index('id="replay-window-next"') < controls.index('id="replay-reset"')
    assert 'id="replay-time"' not in controls


def test_timeline_uses_scroll_instead_of_pagination_and_retains_task_observation_time() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    mission = (STATIC_DIR / "mission.js").read_text(encoding="utf-8")
    header = html.split('class="dock-header"', 1)[1].split("<article", 1)[0]

    assert 'id="schedule-title"' in header and 'id="satellite-filter"' in header
    assert (
        header.index("Visibility")
        < header.index("Observation")
        < header.index('id="satellite-filter"')
    )
    assert 'id="timeline-title"' not in html
    assert "pageItems" not in script + mission
    assert "bindPager" not in script
    assert "state.pages" not in script + mission
    assert "satellites.forEach" in mission
    assert "root.style.height" in mission
    assert "elements.timeline.scrollTop = scrollTop" in mission
    assert "revealTimelineSatellite" in script + mission
    assert 'id="selected-window"' in html
    assert ">Observation · UTC<" in html


def test_replay_scrubber_is_inside_the_timeline_scale_not_the_map_footer() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    footer = html.split('class="replay-bar"', 1)[1].split("</article>", 1)[0]
    timeline = html.split('class="timeline-scale"', 1)[1].split("</article>", 1)[0]
    mission = (STATIC_DIR / "mission.js").read_text(encoding="utf-8")
    for control in ["replay-scrub"]:
        assert html.count(f'id="{control}"') == 1
        assert f'id="{control}"' in timeline
        assert f'id="{control}"' not in footer
    for control in ["replay-window-prev", "replay-window-next"]:
        assert html.count(f'id="{control}"') == 1
        assert f'id="{control}"' in footer
        assert f'id="{control}"' not in timeline
    assert 'id="timeline-axis"' in timeline
    assert '"--timeline-label-width"' in mission
    assert "previous.replaceWith(root)" in mission
    assert "windowStart + duration * tick / 4" in mission


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
    assert ".workload-track" in stylesheet
    assert ".radar-area" in stylesheet
    assert ".radar-legend" in stylesheet
    assert ".comparison-table" not in stylesheet
    assert ".audit-grid" not in stylesheet
    assert ".metric-grid" not in stylesheet
    assert ".metric-details" in stylesheet
    assert ".center-workspace" in stylesheet
    assert ".analysis-dock" in stylesheet
    assert ".command-card::after" in stylesheet
    assert "pointer-events: none" in stylesheet
    assert ".header-rule" in stylesheet
    assert "--panel-header:" in stylesheet
    assert "--panel-radius:" in stylesheet
    assert "--control-active:" in stylesheet
    assert "height: 100dvh" in stylesheet
    assert "overscroll-behavior: none" in stylesheet
    assert stylesheet.count("overflow-y: auto") == 2
    assert "overscroll-behavior: contain" in stylesheet
    assert "scrollbar-width: thin" in stylesheet
    assert "overflow-x: auto" not in stylesheet
    assert "min-width: 0" in stylesheet
    assert "@media (max-width: 640px)" in stylesheet
    assert ":focus-visible" in stylesheet


def test_web_typography_is_self_hosted_and_density_has_one_source_of_truth() -> None:
    import hashlib

    stylesheet = (STATIC_DIR / "app.css").read_text(encoding="utf-8")
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    mission = (STATIC_DIR / "mission.js").read_text(encoding="utf-8")
    font = (STATIC_DIR / "fonts" / "InterVariable.woff2").read_bytes()

    assert font.startswith(b"wOF2")
    assert hashlib.sha256(font).hexdigest() == (
        "693b77d4f32ee9b8bfc995589b5fad5e99adf2832738661f5402f9978429a8e3"
    )
    assert "SIL OPEN FONT LICENSE" in (STATIC_DIR / "fonts" / "OFL.txt").read_text()
    assert 'href="./fonts/InterVariable.woff2" as="font"' in html
    assert "font-variant-numeric: tabular-nums" in stylesheet
    assert "document.fonts.load" in script
    assert "font: '500 12px \"Inter\", sans-serif'" in mission
    assert 'satellite_id.split("_")[0]' not in mission
    for token in [
        "timeline-row-height",
        "workload-row-height",
    ]:
        assert f"--{token}:" in stylesheet
        assert f'layoutSize("{token}")' in script + mission
    assert "height: var(--target-row-height)" in stylesheet


def test_chart_depth_is_native_svg_and_does_not_replace_metric_geometry() -> None:
    mission = (STATIC_DIR / "mission.js").read_text(encoding="utf-8")
    stylesheet = (STATIC_DIR / "app.css").read_text(encoding="utf-8")
    for token in [
        "panel-radius",
        "control-radius",
        "panel-header",
        "control-surface",
        "control-active",
    ]:
        assert f"--{token}:" in stylesheet
    assert "appendChartGradient" in mission
    assert "appendChartDepth" in mission
    assert 'svgElement("feDropShadow"' in mission
    assert 'class: "radar-plinth", "aria-hidden": "true"' in mission
    assert '"--series-fill"' in mission
    assert "const filledWidth = row.load / maximum * barWidth" in mission
    assert "width: filledWidth" in mission
    assert "radius * metric.score" in mission
    assert "perspective(" not in stylesheet


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
