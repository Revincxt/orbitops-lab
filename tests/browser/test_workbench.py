"""Opt-in browser checks against the single-scenario EOS-Bench demo.

Install Playwright and run ORBITOPS_BROWSER_TESTS=1 pytest tests/browser.
Chrome is used by default; ORBITOPS_BROWSER_EXECUTABLE can select another binary.
Remote geometry dependencies are blocked to exercise the offline fallback.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from threading import Thread
from typing import Any

import pytest
from orbitops.web import LabApplication
from orbitops.web.server import make_server

from scripts.build_pages import build_dataset

pytestmark = pytest.mark.skipif(
    os.environ.get("ORBITOPS_BROWSER_TESTS") != "1",
    reason="browser verification is opt-in",
)
ROOT = Path(__file__).parents[2]


@pytest.fixture(scope="module")
def lab_url() -> Iterator[str]:
    server = make_server(ROOT / "scenarios", port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as automation:
        executable = os.environ.get("ORBITOPS_BROWSER_EXECUTABLE")
        options = {"executable_path": executable} if executable else {"channel": "chrome"}
        instance = automation.chromium.launch(headless=True, **options)
        try:
            yield instance
        finally:
            instance.close()


@pytest.fixture
def page(browser: Any) -> Iterator[Any]:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    context.route("https://cesium.com/**", lambda route: route.abort())
    context.route("https://gibs.earthdata.nasa.gov/**", lambda route: route.abort())
    tab = context.new_page()
    errors: list[str] = []
    tab.on("pageerror", lambda error: errors.append(str(error)))
    try:
        yield tab
        assert not errors, errors
    finally:
        context.close()


def ready(page: Any, url: str) -> None:
    reference_ready(page, url)


def assert_single_screen(page: Any) -> None:
    dimensions = page.evaluate("""() => ({
      width: innerWidth, height: innerHeight,
      scrollWidth: document.documentElement.scrollWidth,
      scrollHeight: document.documentElement.scrollHeight,
      x: scrollX, y: scrollY,
      scrollingPanels: [...document.querySelectorAll('main *')].filter(node => {
        const style = getComputedStyle(node);
        return /auto|scroll/.test(style.overflowY) && node.scrollHeight > node.clientHeight + 1;
      }).map(node => node.id || node.className)
    })""")
    assert dimensions["scrollWidth"] == dimensions["width"], dimensions
    assert dimensions["scrollHeight"] == dimensions["height"], dimensions
    assert dimensions["x"] == dimensions["y"] == 0, dimensions
    assert dimensions["scrollingPanels"] == [], dimensions


@pytest.mark.parametrize(
    ("width", "height"),
    [
        (1920, 1080),
        (1440, 900),
        (1366, 768),
        (1280, 720),
        (1024, 768),
        (800, 600),
        (390, 844),
        (375, 667),
    ],
)
def test_analysis_views_fit_without_scrolling(
    page: Any,
    lab_url: str,
    width: int,
    height: int,
) -> None:
    page.set_viewport_size({"width": width, "height": height})
    ready(page, lab_url)
    assert page.locator("#mission-globe").get_attribute("data-engine") == "fallback"
    for name in ["timeline", "comparison"]:
        page.locator(f"#tab-{name}").click()
        page.wait_for_timeout(80)
        assert page.locator(f"#pane-{name}").is_visible()
        assert_single_screen(page)
    page.mouse.move(width // 2, height - 80)
    page.mouse.wheel(0, 800)
    assert_single_screen(page)
    if width <= 1000:
        page.locator("#workspace-tasks").click()
    page.wait_for_timeout(80)
    assert page.locator("#run-button").is_visible()
    assert page.evaluate("""() => {
      const container = document.getElementById('target-list').getBoundingClientRect();
      return [...document.querySelectorAll('.target-row')].every(row =>
        row.getBoundingClientRect().bottom <= container.bottom + 1);
    }""")
    if width <= 1000:
        page.locator("#workspace-summary").click()
        assert page.locator("#inspector").is_visible()
        assert not page.locator("#experiment").is_visible()
        page.locator("#workspace-map").click()
        assert not page.locator("#inspector").is_visible()


def collect_pages(page: Any, name: str, selector: str) -> set[str]:
    seen: set[str] = set()
    for _ in range(70):
        seen.update(
            page.locator(selector).evaluate_all("nodes => nodes.map(node => node.dataset.taskId)")
        )
        if page.locator(f"#{name}-next").is_disabled():
            return seen
        page.locator(f"#{name}-next").click()
    raise AssertionError("pagination did not terminate")


def reference_ready(page: Any, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_function(
        "state.currentPayload?.scenario.scenario_id === 'eos-s1-20-500' && !state.busy"
    )


@pytest.mark.parametrize(
    ("width", "height"),
    [(1920, 1080), (1440, 900), (1366, 768), (800, 600), (390, 844), (375, 667)],
)
def test_reference_views_keep_all_data_reachable_without_scrolling(
    page: Any, lab_url: str, width: int, height: int
) -> None:
    page.set_viewport_size({"width": width, "height": height})
    reference_ready(page, lab_url)
    assert page.locator(".map-satellite").count() == 20
    assert page.locator(".map-marker").count() == 500
    for name in ["timeline", "comparison"]:
        page.locator(f"#tab-{name}").click()
        assert_single_screen(page)
    if width <= 1000:
        page.locator("#workspace-tasks").click()
    page.locator("#target-search").fill("M500")
    assert page.locator(".target-row").count() == 1
    page.locator(".target-row").click()
    assert page.locator("#selected-id").inner_text() == "M500"
    assert_single_screen(page)


def test_reference_half_open_task_states_utc_and_no_local_solves(page: Any, lab_url: str) -> None:
    solve_requests: list[str] = []
    page.on(
        "request",
        lambda request: (
            solve_requests.append(request.url)
            if request.method == "POST" and request.url.endswith("/api/solve")
            else None
        ),
    )
    reference_ready(page, lab_url)
    assert page.evaluate("state.currentPayload.evaluation.TP") == 2816
    assert page.evaluate("state.currentPayload.result.metrics.completed_tasks") == 488
    assert page.evaluate("state.currentPayload.evaluation.TM.toFixed(3)") == "0.307"
    assert page.locator("#seed-input").count() == 0
    page.locator("#target-search").fill("M350")
    page.locator(".target-row").click()
    assert page.locator("#selected-state").text_content() == "Observing"
    assert "12:00:00 UTC" in page.locator("#replay-time").inner_text()
    page.locator("#replay-scrub").evaluate(
        "node => {node.value = 7.9; node.dispatchEvent(new Event('input'));}"
    )
    assert page.locator("#selected-state").text_content() == "Observing"
    assert page.locator('.map-ray[data-task-id="M350"]').count() == 1
    page.locator("#replay-scrub").evaluate(
        "node => {node.value = 8; node.dispatchEvent(new Event('input'));}"
    )
    assert page.locator("#selected-state").text_content() == "Completed"
    assert page.locator('.map-ray[data-task-id="M350"]').count() == 0
    page.locator("#replay-scrub").evaluate(
        "node => {node.value = 43200; node.dispatchEvent(new Event('input'));}"
    )
    assert page.evaluate("state.assignments.size") == 488
    assert page.evaluate(
        "[...state.assignments.values()].every(task => state.replay.time >= task.end_s)"
    )
    assert page.locator("#replay-time").inner_text() == "2025-11-19 00:00:00 UTC"
    assert not solve_requests


def test_reference_all_twenty_satellite_lanes_and_plan_switching(page: Any, lab_url: str) -> None:
    reference_ready(page, lab_url)
    satellites: set[str] = set()
    for _ in range(30):
        satellites.update(
            page.locator(".satellite-lane").evaluate_all(
                "nodes => nodes.map(node => node.dataset.satelliteId)"
            )
        )
        if page.locator("#timeline-next").is_disabled():
            break
        page.locator("#timeline-next").click()
    assert len(satellites) == 20
    page.locator("#satellite-filter").select_option("KENT_RIDGE_1_41167")
    assert page.locator(".satellite-lane").count() == 1
    page.locator("#tab-comparison").click()
    page.locator("#comparison-body button", has_text="SA · profit").click()
    assert page.evaluate("state.currentPayload.evaluation.TP") == 2833
    assert page.evaluate("state.currentPayload.result.metrics.completed_tasks") == 493
    assert page.evaluate("state.currentPayload.result.validation.is_feasible") is None
    assert "Objectives differ" in page.locator("#comparison-context").inner_text()
    assert page.evaluate("state.currentPayload.result.validation.is_feasible") is None
    with page.expect_download() as event:
        page.locator("#export-run").click()
    exported = json.loads(Path(event.value.path()).read_text())
    assert exported["provenance"]["revision"] == "ee282656e8b2f6fd0d3cf84677b40966e2780ef3"
    assert exported["result"]["validation"]["is_feasible"] is None
    assert_single_screen(page)


def test_plan_reload_resets_playback_but_never_changes_scenario(page: Any, lab_url: str) -> None:
    reference_ready(page, lab_url)
    page.locator("#replay-speed").select_option("900")
    page.locator("#replay-play").click()
    page.wait_for_function("Number(document.getElementById('replay-scrub').value) > 100")
    page.locator("#replay-play").click()
    paused = page.locator("#replay-scrub").input_value()
    page.wait_for_timeout(250)
    assert page.locator("#replay-scrub").input_value() == paused
    page.locator("#solver-select").select_option("eos-ppo-profit")
    assert page.locator("#pending-state").is_visible()
    page.keyboard.press("Control+Enter")
    assert page.evaluate("state.currentPayload.result.metrics.completed_tasks") == 492
    assert page.locator("#replay-scrub").input_value() == "0"
    assert page.locator(".map-satellite").count() == 20
    assert page.locator(".map-marker").count() == 500
    assert not page.locator("#pending-state").is_visible()
    assert_single_screen(page)


@pytest.mark.parametrize("timezone", ["UTC", "Asia/Shanghai"])
def test_reference_time_display_does_not_depend_on_browser_timezone(
    browser: Any, lab_url: str, timezone: str
) -> None:
    context = browser.new_context(timezone_id=timezone, viewport={"width": 1440, "height": 900})
    context.route("https://cesium.com/**", lambda route: route.abort())
    context.route("https://gibs.earthdata.nasa.gov/**", lambda route: route.abort())
    try:
        tab = context.new_page()
        reference_ready(tab, lab_url)
        assert tab.locator("#replay-time").inner_text() == "2025-11-18 12:00:00 UTC"
        tab.locator("#replay-scrub").evaluate(
            "node => {node.value = 14400; node.dispatchEvent(new Event('input'));}"
        )
        assert tab.locator("#replay-time").inner_text() == "2025-11-18 16:00:00 UTC"
    finally:
        context.close()


def test_static_reference_mode_uses_the_same_archive_without_api_calls(
    page: Any, lab_url: str
) -> None:
    from scripts.import_eos_reference import REVISION

    dataset = build_dataset(LabApplication(ROOT / "scenarios"))
    assert set(dataset) == {"metadata", "reference"}
    requests: list[str] = []
    page.on(
        "request", lambda request: requests.append(request.url) if "/api/" in request.url else None
    )
    page.route(
        "**/deployment-config.js*",
        lambda route: route.fulfill(
            content_type="text/javascript", body='window.ORBITOPS_DEPLOYMENT = {mode: "static"};'
        ),
    )
    page.route("**/pages-data.json", lambda route: route.fulfill(json=dataset))
    reference_ready(page, lab_url)
    assert page.evaluate("state.currentPayload.result.metrics.completed_tasks") == 488
    assert page.evaluate("state.currentPayload.provenance.revision") == REVISION
    page.locator("#solver-select").select_option("eos-ppo-profit")
    page.locator("#run-button").click()
    assert page.evaluate("state.currentPayload.result.metrics.completed_tasks") == 492
    assert not requests
    assert_single_screen(page)


@pytest.mark.parametrize("time", [0, 0.1, 14400, 43199.9, 43200])
def test_reference_orbit_windows_are_present_at_start_and_stay_inside_source(
    page: Any, lab_url: str, time: float
) -> None:
    reference_ready(page, lab_url)
    page.evaluate("time => setReplayTime(time, true)", time)
    windows = page.evaluate("""() => state.currentPayload.replay.orbits.map(orbit => ({
      ...windowForOrbit(orbit), period: orbit.period_s,
      segments: OrbitReplay.trackSegments(
        orbit.samples, windowForOrbit(orbit).start, windowForOrbit(orbit).end)
    }))""")
    assert len(windows) == 20
    for bounds in windows:
        assert 0 <= bounds["start"] <= time <= bounds["end"] <= 43200
        assert bounds["past"] + bounds["future"] == pytest.approx(bounds["period"])
        assert bounds["segments"]
    assert page.locator(".map-orbit polyline").count() >= 20
    if time == 0:
        assert page.locator(".map-track-past").count() == 0
        assert page.locator(".map-track-future").count() >= 20
    elif time == 43200:
        assert page.locator(".map-track-future").count() == 0
    assert_single_screen(page)


def test_orbit_segments_split_at_date_line_without_losing_the_short_arc(
    page: Any, lab_url: str
) -> None:
    reference_ready(page, lab_url)
    segments = page.evaluate("""() => OrbitReplay.trackSegments(
      [[0, 179, 10, 500000], [30, -179, 12, 500000]], 0, 30)
    """)
    assert len(segments) == 2
    assert segments[0][-1] == [15, 180, 11, 500000]
    assert segments[1][0] == [15, -180, 11, 500000]
    for segment in segments:
        assert abs(segment[0][1] - segment[-1][1]) <= 1


@pytest.mark.parametrize(("width", "height"), [(1440, 900), (800, 600), (375, 667)])
def test_map_expansion_and_satellite_keyboard_selection_preserve_single_screen(
    page: Any, lab_url: str, width: int, height: int
) -> None:
    page.set_viewport_size({"width": width, "height": height})
    reference_ready(page, lab_url)
    assert page.locator("#orbit-hud").is_visible()
    assert page.locator("#camera-focus").count() == 0
    assert page.locator("#camera-follow").is_disabled()
    assert page.locator("#view-2d").get_attribute("aria-pressed") == "true"
    assert page.locator(".map-projections button:disabled").count() == 3
    marker = page.locator('.map-satellite[data-satellite-id="ALOS-2_39766"]')
    marker.focus()
    marker.press("Enter")
    assert page.locator("#satellite-name").get_attribute("title") == "ALOS-2_39766"
    assert marker.get_attribute("aria-pressed") == "true"
    page.locator("#toggle-layers").click()
    page.locator("#toggle-sat-labels").click()
    page.keyboard.press("Escape")
    assert page.locator(".satellite-label:visible").count() == 1
    before = page.locator("#mission-globe").bounding_box()["height"]
    page.locator("#expand-map").click()
    assert page.locator(".analysis-dock").is_hidden()
    assert page.locator("#mission-globe").bounding_box()["height"] > before
    assert_single_screen(page)
    page.locator("#expand-map").click()
    assert page.locator(".analysis-dock").is_visible()
    assert_single_screen(page)


@pytest.mark.parametrize("aspect", [3.2, 1, 0.5])
def test_tilted_map_camera_range_contains_world_and_source_altitudes(
    page: Any, lab_url: str, aspect: float
) -> None:
    reference_ready(page, lab_url)
    points = page.evaluate(
        """aspect => {
      const a = 20037508, b = 10018754, h = 876536;
      const pitch = 55 * Math.PI / 180, fovy = Math.PI / 3;
      const distance = OrbitReplay.flatMapRange(a, b, h, pitch, fovy, aspect);
      return [-a,a].flatMap(x => [-b,b].flatMap(y => [0,h].map(z => ({
        horizontal:Math.abs(x) / ((distance + y * Math.cos(pitch) - z * Math.sin(pitch))
          * Math.tan(fovy / 2) * aspect),
        vertical:Math.abs(y * Math.sin(pitch) + z * Math.cos(pitch))
          / ((distance + y * Math.cos(pitch) - z * Math.sin(pitch)) * Math.tan(fovy / 2))
      }))));
    }""",
        aspect,
    )
    assert all(0 < point["horizontal"] < 1 and 0 < point["vertical"] < 1 for point in points)
    assert_single_screen(page)


@pytest.mark.parametrize("query", ["", "?mode=local", "?scenario=showcase-global-30"])
def test_demo_has_only_eos_bench_and_no_irrelevant_controls(
    page: Any, lab_url: str, query: str
) -> None:
    requests: list[str] = []
    page.on("request", lambda request: requests.append(request.url))
    reference_ready(page, lab_url + query)
    for removed in [
        "scenario-select",
        "seed-input",
        "budget-input",
        "scenario-context",
        "solver-description",
        "model-note",
        "runtime",
        "globe-coordinate",
    ]:
        assert page.locator(f"#{removed}").count() == 0
    assert page.locator("#solver-select option").count() == 4
    assert all(
        "eos-" in value
        for value in page.locator("#solver-select option").evaluate_all(
            "nodes => nodes.map(node => node.value)"
        )
    )
    assert not any(
        path in url for url in requests for path in ["/api/scenarios", "/api/solvers", "/api/solve"]
    )
    assert page.locator("#check-context").count() == 0
    assert page.evaluate("state.currentPayload.result.validation.is_feasible") is None
    assert_single_screen(page)


def test_all_reference_targets_remain_reachable_and_selection_is_linked(
    page: Any, lab_url: str
) -> None:
    reference_ready(page, lab_url)
    assert len(collect_pages(page, "target", ".target-row")) == 500
    task = page.locator(".target-row").last
    task_id = task.get_attribute("data-task-id")
    task.click()
    assert page.locator("#selected-id").inner_text() == task_id
    assert "is-selected" in page.locator(f'.map-marker[data-task-id="{task_id}"]').get_attribute(
        "class"
    )
    page.locator("#tab-timeline").focus()
    page.keyboard.press("ArrowRight")
    assert page.locator("#tab-comparison").get_attribute("aria-selected") == "true"


def test_layer_menu_keyboard_dismissal_and_preserved_layer_controls(
    page: Any, lab_url: str
) -> None:
    reference_ready(page, lab_url)
    assert page.locator("#layer-options").is_hidden()
    page.locator("#toggle-layers").focus()
    page.keyboard.press("Enter")
    assert page.locator("#layer-options").is_visible()
    page.keyboard.press("Tab")
    assert page.locator("#toggle-targets").evaluate("node => node === document.activeElement")
    page.keyboard.press("Enter")
    assert page.locator(".map-marker").first.is_hidden()
    assert page.locator("#toggle-targets").get_attribute("aria-pressed") == "false"
    page.locator("#toggle-targets").click()
    page.locator("#toggle-track").click()
    assert page.locator(".map-orbit").first.is_hidden()
    page.locator("#toggle-track").click()
    page.keyboard.press("Escape")
    assert page.locator("#layer-options").is_hidden()
    assert page.locator("#toggle-layers").evaluate("node => node === document.activeElement")
    page.locator("#toggle-layers").click()
    page.locator("#tab-comparison").click()
    assert page.locator("#layer-options").is_hidden()


@pytest.mark.parametrize(("width", "height"), [(1440, 900), (1024, 768), (800, 600), (375, 667)])
def test_inspector_details_and_map_toolbar_fit_without_clipping(
    page: Any, lab_url: str, width: int, height: int
) -> None:
    page.set_viewport_size({"width": width, "height": height})
    reference_ready(page, lab_url)
    if width <= 1000:
        page.locator("#workspace-summary").click()
    for name in ["selection", "evaluation"]:
        page.locator(f"#tab-{name}").click()
        page.wait_for_timeout(80)
        assert page.evaluate(
            """name => {
          const panel = document.getElementById('inspector-' + name);
          return panel.scrollHeight <= panel.clientHeight + 1;
        }""",
            name,
        )
        assert_single_screen(page)
    if width <= 1000:
        page.locator("#workspace-map").click()
    assert (
        page.locator("#mission-globe").bounding_box()["height"]
        > (page.locator(".analysis-dock").bounding_box()["height"])
    )
    page.locator("#toggle-layers").click()
    assert page.locator("#toggle-sat-labels").is_visible()
    assert_single_screen(page)


def test_missing_reference_archive_reports_error_without_local_fallback(
    page: Any, lab_url: str
) -> None:
    requests: list[str] = []
    page.on("request", lambda request: requests.append(request.url))
    page.route("**/api/reference/data", lambda route: route.fulfill(body="null"))
    page.goto(lab_url + "?mode=local", wait_until="domcontentloaded")
    page.wait_for_function("document.getElementById('status').classList.contains('error')")
    assert "EOS-Bench reference data is unavailable" in page.locator("#status").inner_text()
    assert page.locator("#run-button").is_disabled()
    assert page.locator("#solver-select").is_disabled()
    assert page.locator("#export-run").is_disabled()
    assert not any("/api/scenarios" in url or "/api/solve" in url for url in requests)


def test_workload_selection_matches_satellite_highlight(page: Any, lab_url: str) -> None:
    reference_ready(page, lab_url)
    bar = page.locator(".workload-row").first
    satellite = bar.get_attribute("data-satellite-id")
    bar.focus()
    bar.press("Enter")
    assert page.locator("#satellite-name").get_attribute("title") == satellite
    assert (
        page.locator(f'.workload-row[data-satellite-id="{satellite}"]').get_attribute(
            "aria-pressed"
        )
        == "true"
    )
    assert page.locator(".workload-bar.is-selected").count() == 1
