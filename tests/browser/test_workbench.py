"""Opt-in browser checks against the real local scheduling API.

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
    page.goto(url + "?mode=local", wait_until="domcontentloaded")
    page.wait_for_function(
        "document.getElementById('metric-feasible').textContent === 'PASS' "
        "&& !document.getElementById('run-button').disabled"
    )


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
    for name in ["timeline", "comparison", "audit", "learning"]:
        page.locator(f"#tab-{name}").click()
        page.wait_for_timeout(80)
        assert page.locator(f"#pane-{name}").is_visible()
        assert_single_screen(page)
    page.mouse.move(width // 2, height - 80)
    page.mouse.wheel(0, 800)
    assert_single_screen(page)
    if width <= 1000:
        page.locator("#toggle-config").click()
    page.wait_for_timeout(80)
    assert page.locator("#run-button").is_visible()
    assert page.evaluate("""() => {
      const container = document.getElementById('target-list').getBoundingClientRect();
      return [...document.querySelectorAll('.target-row')].every(row =>
        row.getBoundingClientRect().bottom <= container.bottom + 1);
    }""")
    page.locator("#toggle-inspector").click()
    if width <= 1000:
        assert page.locator("#inspector").is_visible()
        assert not page.locator("#experiment").is_visible()
        page.keyboard.press("Escape")
        assert not page.locator("#inspector").is_visible()


def collect_pages(page: Any, name: str, selector: str) -> set[str]:
    seen: set[str] = set()
    for _ in range(35):
        seen.update(
            page.locator(selector).evaluate_all("nodes => nodes.map(node => node.dataset.taskId)")
        )
        if page.locator(f"#{name}-next").is_disabled():
            return seen
        page.locator(f"#{name}-next").click()
    raise AssertionError("pagination did not terminate")


def test_all_thirty_targets_remain_reachable_and_selection_is_linked(
    page: Any,
    lab_url: str,
) -> None:
    ready(page, lab_url)
    page.locator("#scenario-select").select_option("showcase-global-30")
    page.locator("#solver-select").select_option("greedy-insertion")
    assert page.locator("#pending-state").is_visible()
    page.keyboard.press("Control+Enter")
    page.wait_for_function(
        "document.getElementById('mission-id').textContent === 'showcase-global-30'"
    )
    assert (
        page.locator('#solver-select option[value="brute-force"]').get_attribute("disabled") == ""
    )
    assert (
        page.locator('#solver-select option[value="branch-and-bound"]').get_attribute("disabled")
        == ""
    )
    catalog = collect_pages(page, "target", ".target-row")
    timeline = collect_pages(page, "timeline", ".timeline-row")
    assert len(catalog) == len(timeline) == 30
    assert catalog == timeline
    target = page.locator(".target-row").first
    task_id = target.get_attribute("data-task-id")
    target.click()
    assert page.locator("#selected-id").inner_text() == task_id
    assert (
        page.locator(f'.map-marker[data-task-id="{task_id}"]')
        .get_attribute("class")
        .endswith("is-selected")
    )
    row = page.locator(".timeline-row").last
    row.focus()
    row.press("Enter")
    assert page.locator("#selected-id").inner_text() == row.get_attribute("data-task-id")
    page.locator("#tab-timeline").focus()
    page.keyboard.press("ArrowRight")
    assert page.locator("#tab-comparison").get_attribute("aria-selected") == "true"
    assert not page.locator("#pending-state").is_visible()
    assert_single_screen(page)


def test_result_export_busy_guard_layers_and_failure_recovery(page: Any, lab_url: str) -> None:
    ready(page, lab_url)
    page.locator("#toggle-targets").click()
    assert page.locator(".map-marker").first.is_hidden()
    page.locator("#toggle-targets").click()
    page.locator("#toggle-track").click()
    assert page.locator(".map-sequence").is_hidden()
    page.locator("#toggle-track").click()
    page.locator("#seed-input").fill("43")
    assert page.locator("#pending-state").is_visible()
    page.locator("#seed-input").fill("42")
    assert not page.locator("#pending-state").is_visible()
    with page.expect_download() as event:
        page.locator("#export-run").click()
    exported = json.loads(Path(event.value.path()).read_text())
    assert exported["scenario"]["scenario_id"] == "showcase-resources-10"
    assert exported["result"]["validation"]["is_feasible"] is True
    held_requests: list[Any] = []
    page.route("**/api/solve", lambda route: held_requests.append(route))
    page.locator("#run-button").click()
    assert page.locator("#run-button").is_disabled()
    assert page.locator("#scenario-select").is_disabled()
    page.keyboard.press("Control+Enter")
    page.keyboard.press("Control+Enter")
    assert len(held_requests) == 1
    held_requests[0].fulfill(status=200, json=exported)
    page.wait_for_function("!document.getElementById('run-button').disabled")
    page.unroute("**/api/solve")
    page.route(
        "**/api/solve",
        lambda route: route.fulfill(
            status=500,
            content_type="application/json",
            body='{"error":"Controlled failure"}',
        ),
    )
    page.locator("#run-button").click()
    page.wait_for_function("document.getElementById('status').textContent === 'Controlled failure'")
    assert page.locator("#run-button").is_enabled()
    assert page.locator("#scenario-select").is_enabled()
    assert page.locator("#metric-feasible").inner_text() == "PASS"
    page.unroute("**/api/solve")
    page.locator("#solver-select").select_option("greedy-insertion")
    page.locator("#run-button").click()
    page.wait_for_function(
        "document.getElementById('record-method').textContent === 'greedy-insertion'"
    )
    assert page.locator("#metric-feasible").inner_text() == "PASS"
    page.locator("#tab-comparison").click()
    page.locator("#comparison-body button", has_text="q-learning").click()
    assert page.locator("#record-method").inner_text() == "q-learning (hybrid)"
    assert_single_screen(page)


def test_pages_mode_preserves_recorded_budgets_and_all_comparison_rows(
    page: Any,
    lab_url: str,
) -> None:
    dataset = build_dataset(LabApplication(ROOT / "scenarios"))
    api_requests: list[str] = []
    page.on(
        "request",
        lambda request: api_requests.append(request.url) if "/api/" in request.url else None,
    )
    page.route(
        "**/deployment-config.js*",
        lambda route: route.fulfill(
            content_type="text/javascript",
            body='window.ORBITOPS_DEPLOYMENT = {mode: "static"};',
        ),
    )
    page.route("**/pages-data.json", lambda route: route.fulfill(json=dataset))
    ready(page, lab_url)
    assert not api_requests
    assert page.locator("#seed-input").is_disabled()
    assert page.locator("#budget-input").is_disabled()
    assert page.locator("#budget-input").input_value() == "120"
    assert "precomputed" in page.locator("#deployment-mode").inner_text()
    page.locator("#tab-comparison").click()
    methods: set[str] = set()
    for _ in range(12):
        methods.update(page.locator("#comparison-body tr td:first-child").all_text_contents())
        if page.locator("#comparison-next").is_disabled():
            break
        page.locator("#comparison-next").click()
    assert len(methods) == len(dataset["solvers"]["solvers"])
    page.locator("#solver-select").select_option("greedy-insertion")
    page.locator("#run-button").click()
    page.wait_for_function(
        "document.getElementById('record-method').textContent === 'greedy-insertion'"
    )
    assert page.locator("#budget-input").input_value() == "250"
    assert page.locator("#budget-input").is_disabled()
    assert page.locator("#seed-input").is_disabled()
    assert not api_requests
    assert_single_screen(page)


def reference_ready(page: Any, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_function(
        "document.getElementById('mission-id').textContent === 'eos-s1-20-500' "
        "&& document.getElementById('metric-feasible').textContent === 'N/A'"
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
    for name in ["timeline", "comparison", "audit", "learning"]:
        page.locator(f"#tab-{name}").click()
        assert_single_screen(page)
    if width <= 1000:
        page.locator("#toggle-config").click()
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
    assert page.locator("#metric-value").inner_text() == "2816.0"
    assert page.locator("#metric-tasks").inner_text() == "488/500"
    assert page.locator("#metric-slew").inner_text() == "0.307"
    assert page.locator("#seed-input").is_disabled()
    assert page.locator("#seed-input").input_value() == ""
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
    assert "488/488 completed" in page.locator("#replay-progress").inner_text()
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
    assert page.locator("#metric-value").inner_text() == "2833.0"
    assert page.locator("#metric-tasks").inner_text() == "493/500"
    assert page.locator("#metric-feasible").inner_text() == "N/A"
    assert "objectives differ" in page.locator("#comparison-context").inner_text()
    page.locator("#tab-audit").click()
    assert "Full feasibility not verified" in page.locator("#validation-list").inner_text()
    with page.expect_download() as event:
        page.locator("#export-run").click()
    exported = json.loads(Path(event.value.path()).read_text())
    assert exported["provenance"]["revision"] == "ee282656e8b2f6fd0d3cf84677b40966e2780ef3"
    assert exported["result"]["validation"]["is_feasible"] is None
    assert_single_screen(page)


def test_reference_switch_to_local_restores_solver_contract_and_paused_clock(
    page: Any, lab_url: str
) -> None:
    reference_ready(page, lab_url)
    page.locator("#replay-speed").select_option("900")
    page.locator("#replay-play").click()
    page.wait_for_function("Number(document.getElementById('replay-scrub').value) > 100")
    page.locator("#replay-play").click()
    paused = page.locator("#replay-scrub").input_value()
    page.wait_for_timeout(250)
    assert page.locator("#replay-scrub").input_value() == paused
    page.locator("#scenario-select").select_option("showcase-resources-10")
    assert page.locator("#seed-input").is_enabled()
    assert page.locator("#seed-input").input_value() == "42"
    page.locator("#solver-select").select_option("greedy-insertion")
    page.locator("#run-button").click()
    page.wait_for_function("document.getElementById('metric-feasible').textContent === 'PASS'")
    assert page.locator(".map-satellite").count() == 0
    assert page.locator(".map-ray").count() == 0
    assert page.locator("#replay-scrub").input_value() == "0"
    assert page.locator("#metric-balance").inner_text() == "N/A · single satellite"
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

    archive = json.loads((ROOT / "data" / "eos-bench" / "reference.json").read_text())
    dataset = {
        "metadata": {"seed": 42, "evaluation_budget": 250},
        "scenarios": {"scenarios": []},
        "solvers": {"solvers": []},
        "runs": {},
        "omissions": {},
        "reference": archive,
    }
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
    assert page.locator("#metric-tasks").inner_text() == "488/500"
    assert page.locator("#record-revision").get_attribute("title").startswith(REVISION)
    page.locator("#solver-select").select_option("eos-ppo-profit")
    page.locator("#run-button").click()
    assert page.locator("#metric-tasks").inner_text() == "492/500"
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
    assert page.locator("#camera-focus").is_disabled()
    assert page.locator("#camera-follow").is_disabled()
    marker = page.locator('.map-satellite[data-satellite-id="ALOS-2_39766"]')
    marker.focus()
    marker.press("Enter")
    assert page.locator("#satellite-name").get_attribute("title") == "ALOS-2_39766"
    assert marker.get_attribute("aria-pressed") == "true"
    page.locator("#toggle-sat-labels").click()
    assert page.locator(".satellite-label:visible").count() == 1
    before = page.locator("#mission-globe").bounding_box()["height"]
    page.locator("#expand-map").click()
    assert page.locator(".analysis-dock").is_hidden()
    assert page.locator("#mission-globe").bounding_box()["height"] > before
    assert_single_screen(page)
    page.locator("#expand-map").click()
    assert page.locator(".analysis-dock").is_visible()
    assert_single_screen(page)
