"""Opt-in browser checks against the single-scenario EOS-Bench demo.

Install Playwright and run ORBITOPS_BROWSER_TESTS=1 pytest tests/browser.
Chrome is used by default; ORBITOPS_BROWSER_EXECUTABLE can select another binary.
Remote geometry dependencies are blocked to exercise the offline fallback.
"""

from __future__ import annotations

import math
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
    server = make_server(ROOT / "data/eos-bench/reference.json", port=0)
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
    assert set(dimensions["scrollingPanels"]) <= {
        "target-list",
        "timeline-chart",
        "resource-chart",
    }, dimensions


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
    assert page.locator("#pane-timeline").is_visible()
    assert_single_screen(page)
    page.mouse.move(width // 2, height - 80)
    page.mouse.wheel(0, 800)
    assert_single_screen(page)
    if width <= 1000:
        page.locator("#workspace-tasks").click()
    page.wait_for_timeout(80)
    assert page.get_by_label("Optimization Algorithm", exact=True).is_visible()
    assert page.locator("#target-list, #resource-chart").evaluate_all(
        "nodes => nodes.every(node => getComputedStyle(node).visibility === 'visible')"
    )
    if width <= 1000:
        page.locator("#workspace-summary").click()
    assert page.locator("#comparison-chart").is_visible()
    assert page.evaluate("""() => {
      const container = document.getElementById('target-list');
      const radar = document.getElementById('comparison-chart');
      const header = document.querySelector('.masthead');
      const compact = innerWidth <= 700 && innerHeight <= 650;
      return container.clientHeight >= 48 && radar.clientHeight >= (compact ? 80 : 120)
        && header.scrollWidth <= header.clientWidth + 1;
    }""")
    if width <= 1000:
        page.locator("#workspace-summary").click()
        assert page.locator("#inspector").is_visible()
        assert not page.locator("#experiment").is_visible()
        page.locator("#workspace-map").click()
        assert not page.locator("#inspector").is_visible()


def reference_ready(page: Any, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_function(
        "state.currentPayload?.scenario.scenario_id === 'eos-s1-20-500' && !state.busy"
    )


def assert_centered_playback_controls(page: Any) -> None:
    group = page.get_by_role("group", name="Playback controls", exact=True)
    assert group.is_visible()
    assert group.locator("button, select").evaluate_all("nodes => nodes.map(n => n.id)") == [
        "replay-window-prev",
        "replay-play",
        "replay-window-next",
        "replay-reset",
        "replay-direction",
        "replay-speed",
    ]
    assert group.evaluate("""node => {
      const group = node.getBoundingClientRect();
      const frame = document.querySelector('.globe-frame').getBoundingClientRect();
      const bar = node.closest('.replay-bar'), footer = bar.getBoundingClientRect();
      const controls = [...node.querySelectorAll('button,select')]
        .map(n => n.getBoundingClientRect());
      const touch = matchMedia('(pointer: coarse)').matches;
      return Math.abs((group.left + group.right - frame.left - frame.right) / 2) < 1
        && footer.height === 46 && group.height === (touch ? 34 : 32)
        && group.top >= footer.top && group.bottom <= footer.bottom
        && !bar.querySelector('#replay-scrub') && Math.abs(frame.bottom - footer.top) < 1
        && bar.scrollHeight <= bar.clientHeight && node.scrollWidth <= node.clientWidth
        && controls.every((r, index) => r.left >= group.left && r.right <= group.right
          && r.top >= group.top && r.bottom <= group.bottom
          && Math.abs((r.top + r.bottom - group.top - group.bottom) / 2) < 1
          && r.height === (touch ? 30 : 26)
          && (!index || controls[index - 1].right + 1 <= r.left));
    }""")


def assert_timeline_playback_alignment(page: Any) -> None:
    assert page.locator("#pane-timeline .timeline-scale #replay-scrub").count() == 1
    assert page.locator(".replay-bar #replay-scrub").count() == 0
    assert page.locator("#timeline-chart").evaluate("""node => {
      const lines = [...node.querySelectorAll('.timeline-lanes > .chart-grid')]
        .map(line => line.getBoundingClientRect().x);
      const slider = node.querySelector('#replay-scrub');
      const range = slider.getBoundingClientRect();
      const controls = slider.parentElement;
      const track = getComputedStyle(controls, '::before');
      const bounds = controls.getBoundingClientRect();
      const position = (Number(slider.value)-Number(slider.min))
        / (Number(slider.max)-Number(slider.min));
      const expected = range.left + 5 + position * (range.width - 10);
      const cursor = node.querySelector('.time-cursor');
      return Math.abs(range.left + 5 - lines[0]) < 1
        && Math.abs(range.right - 5 - lines[4]) < 1
        && Math.abs(bounds.left + parseFloat(track.left) - lines[0]) < 1
        && Math.abs(bounds.right - parseFloat(track.right) - lines[4]) < 1
        && (cursor.hasAttribute('hidden')
          || Math.abs(cursor.getBoundingClientRect().x - expected) < 1)
        && [...node.querySelectorAll('.timeline-axis text')].every((text, i) => {
          const point = text.ownerSVGElement.createSVGPoint();
          point.x = Number(text.getAttribute('x'));
          return Math.abs(point.matrixTransform(text.getScreenCTM()).x - lines[i]) < 1;
        });
    }""")


@pytest.mark.parametrize(
    ("width", "height"),
    [(1920, 1080), (1440, 900), (1366, 768), (1280, 720), (1024, 768), (800, 600), (375, 667)],
)
def test_playback_group_is_centered_and_keeps_speed_direction_and_keyboard_controls(
    page: Any, lab_url: str, width: int, height: int
) -> None:
    page.set_viewport_size({"width": width, "height": height})
    reference_ready(page, lab_url)
    source = page.evaluate("JSON.stringify(state.currentPayload)")
    map_bounds = page.locator("#mission-globe").bounding_box()
    assert_centered_playback_controls(page)
    page.locator("#replay-speed").select_option("300")
    assert page.evaluate("state.replay.speed") == 300
    play = page.locator("#replay-play")
    play.focus()
    play.press("Enter")
    assert play.get_attribute("aria-pressed") == "true"
    assert play.get_attribute("aria-label") == "Pause mission replay"
    play.press("Enter")
    assert play.get_attribute("aria-pressed") == "false"
    assert not page.evaluate("state.replay.playing")
    direction = page.locator("#replay-direction")
    direction.focus()
    direction.press("Space")
    assert direction.get_attribute("aria-pressed") == "true"
    assert page.evaluate("state.replay.direction") == -1
    page.locator("#replay-reset").click()
    assert page.evaluate("state.replay.time") == 0
    assert page.locator("#replay-time").inner_text() == "2025-11-18 12:00:00 UTC"
    assert_centered_playback_controls(page)
    assert page.locator("#mission-globe").bounding_box() == map_bounds
    page.locator("#expand-map").click()
    assert_centered_playback_controls(page)
    page.locator("#expand-map").click()
    assert page.locator("#mission-globe").bounding_box() == map_bounds
    assert page.evaluate("JSON.stringify(state.currentPayload)") == source
    assert_single_screen(page)


@pytest.mark.parametrize(("width", "height"), [(390, 844), (375, 667)])
def test_touch_playback_group_stays_centered_inside_the_compact_footer(
    browser: Any, lab_url: str, width: int, height: int
) -> None:
    context = browser.new_context(
        viewport={"width": width, "height": height}, is_mobile=True, has_touch=True
    )
    context.route("https://cesium.com/**", lambda route: route.abort())
    context.route("https://gibs.earthdata.nasa.gov/**", lambda route: route.abort())
    try:
        page = context.new_page()
        reference_ready(page, lab_url)
        assert page.evaluate("matchMedia('(pointer: coarse)').matches")
        assert_centered_playback_controls(page)
        page.locator("#replay-speed").select_option("900")
        assert page.evaluate("state.replay.speed") == 900
        page.locator("#replay-direction").tap()
        assert page.evaluate("state.replay.direction") == -1
        page.locator("#replay-play").tap()
        assert page.evaluate("state.replay.playing")
        page.locator("#replay-play").tap()
        assert not page.evaluate("state.replay.playing")
        assert_centered_playback_controls(page)
        assert_single_screen(page)
    finally:
        context.close()


@pytest.mark.parametrize(
    ("width", "height"),
    [
        (1920, 1080),
        (1440, 900),
        (1280, 720),
        (1024, 768),
        (1440, 600),
        (1000, 700),
        (800, 600),
        (701, 600),
        (700, 700),
        (375, 667),
        (375, 600),
    ],
)
def test_swapped_sidebar_panels_preserve_order_space_and_map_dimensions(
    page: Any, lab_url: str, width: int, height: int
) -> None:
    page.set_viewport_size({"width": width, "height": height})
    reference_ready(page, lab_url)
    map_bounds = page.evaluate("elements.globe.getBoundingClientRect().toJSON()")
    if width <= 1000:
        page.locator("#workspace-tasks").click()
    assert page.locator("#experiment > .command-card").evaluate_all(
        "nodes => nodes.map(node => node.getAttribute('aria-labelledby'))"
    ) == ["targets-title", "resources-title"]
    assert page.locator("#inspector > .command-card").evaluate_all(
        "nodes => nodes.map(node => node.getAttribute('aria-labelledby'))"
    ) == ["comparison-title", "results-title"]
    assert page.evaluate("""() => {
      const panel = document.getElementById('experiment').getBoundingClientRect();
      const task = document.querySelector('.target-catalog').getBoundingClientRect();
      const workload = document.querySelector('.resource-block').getBoundingClientRect();
      const list = elements.targetList.getBoundingClientRect();
      const chart = elements.resources.getBoundingClientRect();
      const tablet = innerWidth >= 701 && innerWidth <= 1000;
      return task.top >= panel.top && task.bottom <= panel.bottom
        && workload.top >= panel.top && workload.bottom <= panel.bottom
        && list.height >= 48 && chart.height >= 120
        && (tablet ? task.right + 7 <= workload.left && task.width >= workload.width
          : task.bottom + 7 <= workload.top && Math.abs(workload.bottom - panel.bottom) < 1);
    }""")
    assert page.locator(".target-row").count() == 500
    assert page.locator("#comparison-legend button").count() == 7
    page.locator("#target-filter").select_option("unassigned")
    assert page.locator(".target-row").count() == 12
    page.locator("#target-filter").select_option("all")
    assert page.locator("#comparison-info, #comparison-scales").count() == 0
    assert page.locator(".comparison-card .section-heading button").count() == 0
    if width <= 1000:
        page.locator("#workspace-summary").click()
    assert page.evaluate("""() => {
      const panel = document.getElementById('inspector').getBoundingClientRect();
      const comparison = document.querySelector('.comparison-card').getBoundingClientRect();
      const summary = document.querySelector('.inspector-card').getBoundingClientRect();
      const radar = elements.comparisonChart.getBoundingClientRect();
      const legend = elements.comparisonLegend.getBoundingClientRect();
      const values = elements.comparisonValues.getBoundingClientRect();
      const tablet = innerWidth >= 701 && innerWidth <= 1000;
      const compact = (innerWidth <= 700 || innerWidth > 1000) && innerHeight <= 650;
      return Math.abs(comparison.top - panel.top) < 1
        && (tablet ? comparison.right + 7 <= summary.left
          && Math.abs(summary.top - panel.top) < 1
          && Math.abs(comparison.bottom - panel.bottom) < 1
          : comparison.bottom + 7 <= summary.top
          && Math.abs(summary.bottom - panel.bottom) < 1)
        && radar.height >= (compact ? 80 : 120)
        && legend.top >= comparison.top && legend.bottom <= values.top
        && legend.left >= comparison.left && legend.right <= comparison.right;
    }""")
    assert page.evaluate("""() => {
      const left = document.getElementById('experiment').getBoundingClientRect();
      const right = document.getElementById('inspector').getBoundingClientRect();
      const task = document.querySelector('.target-catalog').getBoundingClientRect();
      const workload = document.querySelector('.resource-block').getBoundingClientRect();
      const comparison = document.querySelector('.comparison-card').getBoundingClientRect();
      const summary = document.querySelector('.inspector-card').getBoundingClientRect();
      const expected = innerHeight <= 650 ? 256 : Math.min(336, Math.max(272, right.height * .4));
      const expectedWorkload = innerHeight <= 650
        ? Math.min(320, Math.max(272, left.height * .56))
        : Math.min(560, Math.max(320, left.height * .54));
      const near = (a,b) => Math.abs(a-b) < 1;
      if (!near(summary.height, expected)) return false;
      if (innerWidth >= 701 && innerWidth <= 1000) {
        return near(task.height,left.height) && near(workload.height,left.height)
          && near(comparison.height,right.height);
      }
      return near(task.top,comparison.top) && near(workload.bottom,summary.bottom)
        && near(workload.height,expectedWorkload) && workload.height > summary.height;
    }""")
    assert_single_screen(page)
    if width <= 1000:
        page.locator("#workspace-map").click()
    assert page.evaluate("elements.globe.getBoundingClientRect().toJSON()") == map_bounds
    assert_single_screen(page)


def test_decluttered_header_and_static_compass_work_without_the_globe_engine(
    page: Any, lab_url: str
) -> None:
    reference_ready(page, lab_url)
    assert "Mission workspace" not in page.locator(".masthead").inner_text()
    assert page.get_by_role("heading", name="OrbitOps", exact=True).count() == 1
    assert page.locator(".app-title, .header-divider").count() == 0
    assert page.locator("#north-view").is_disabled()
    assert page.locator("#camera-heading").count() == 0
    assert page.locator("#north-view").get_attribute("title") == "Face north"
    assert page.locator(".compass-dial").is_visible()
    assert page.locator(".compass-dial defs linearGradient").count() == 2
    assert page.locator(".compass-dial defs radialGradient").count() == 1
    assert page.locator(".compass-north-label text").text_content() == "N"
    assert page.locator(".compass-inner-ring, .compass-needle-facet, .compass-pivot").count() == 3
    assert page.locator("#north-view").evaluate("""node => {
      const box=node.getBoundingClientRect();
      const dial=node.querySelector('.compass-dial').getBoundingClientRect();
      const buttonStyle=getComputedStyle(node);
      const ringStyle=getComputedStyle(node.querySelector('.compass-inner-ring'));
      return box.width>=44 && box.height>=44 && dial.width===48 && dial.height===48
        && buttonStyle.backgroundImage === 'none'
        && buttonStyle.borderTopWidth === '0px' && buttonStyle.borderRadius === '50%'
        && getComputedStyle(node.querySelector('.compass-bezel')).fill.includes('compass-face')
        && getComputedStyle(node.querySelector('.compass-bezel')).stroke === 'none'
        && ringStyle.strokeDasharray === '18px, 7px' && ringStyle.strokeWidth === '1px'
        && getComputedStyle(node.querySelector('.compass-north')).fill.includes('compass-needle');
    }""")
    assert page.get_by_text("Data attribution", exact=True).count() == 0
    assert_single_screen(page)


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
    assert_single_screen(page)
    if width <= 1000:
        page.locator("#workspace-tasks").click()
    assert page.locator("#target-search").count() == 0
    assert page.locator(".target-row").count() == 500
    page.locator('.target-row[data-task-id="M500"]').click()
    assert page.locator("#selected-id").inner_text() == "M500"
    assert_single_screen(page)


@pytest.mark.parametrize(
    ("width", "height"),
    [(1920, 1080), (1440, 900), (1280, 720), (1024, 768), (800, 600), (375, 667)],
)
def test_task_filter_and_inspector_tabs_fit_their_heading_rows(
    page: Any, lab_url: str, width: int, height: int
) -> None:
    page.set_viewport_size({"width": width, "height": height})
    reference_ready(page, lab_url)
    page.evaluate("document.fonts.ready")
    page.evaluate("() => {setReplayTime(0, true);}")
    original = page.evaluate("JSON.stringify(state.currentPayload)")
    active_count = page.evaluate("""() => [...state.assignments.values()].filter(task =>
      task.start_s <= state.replay.time && state.replay.time < task.end_s).length""")
    assert active_count > 0
    map_bounds = page.evaluate("elements.globe.getBoundingClientRect().toJSON()")
    assert page.locator("#target-search, .catalog-filters").count() == 0
    if width <= 1000:
        page.locator("#workspace-tasks").click()
    task_filter = page.locator("#target-filter")
    assert task_filter.is_visible()
    assert task_filter.evaluate("""node => {
      const heading = node.closest('.section-heading');
      const title = heading.querySelector('#targets-title').getBoundingClientRect();
      const control = node.getBoundingClientRect(), box = heading.getBoundingClientRect();
      return Math.abs((title.top + title.bottom - control.top - control.bottom) / 2) < 1
        && control.left >= title.right + 6 && box.right - control.right <= 16
        && control.top >= box.top && control.bottom <= box.bottom
        && heading.scrollWidth <= heading.clientWidth;
    }""")
    for status, count in [
        ("planned", 488),
        ("unassigned", 12),
        ("active", active_count),
        ("all", 500),
    ]:
        task_filter.select_option(status)
        assert page.locator(".target-row").count() == count
        assert page.evaluate("""() => [...elements.targetList.children].every(row => {
          const filter = document.getElementById('target-filter').value;
          return filter === 'all' || (filter === 'planned'
            ? state.assignments.has(row.dataset.taskId)
            : row.dataset.state === (filter === 'active' ? 'Observing' : 'Unassigned'));
        })""")
    task_filter.select_option("active")
    page.evaluate("() => {setReplayTime(43200, true);}")
    assert page.locator(".target-row").count() == 0
    page.locator("#replay-reset").dispatch_event("click")
    assert page.locator(".target-row").count() == active_count
    task_filter.select_option("all")
    if width <= 1000:
        page.locator("#workspace-summary").click()
    tabs = page.get_by_role("tablist", name="Inspector views")
    assert tabs.is_visible()
    assert tabs.evaluate("""node => {
      const heading = node.closest('.panel-heading');
      const title = heading.querySelector('#results-title').getBoundingClientRect();
      const control = node.getBoundingClientRect(), box = heading.getBoundingClientRect();
      return Math.abs((title.top + title.bottom - control.top - control.bottom) / 2) < 1
        && control.left >= title.right + 6 && box.right - control.right <= 12
        && control.top >= box.top && control.bottom <= box.bottom
        && heading.scrollWidth <= heading.clientWidth
        && [...node.children].every(tab => {
          const r = tab.getBoundingClientRect();
          return r.left >= control.left && r.right <= control.right
            && tab.scrollWidth <= tab.clientWidth;
        });
    }""")
    card_bounds = page.locator(".inspector-card").bounding_box()
    page.locator("#tab-evaluation").click()
    assert page.locator("#inspector-evaluation").is_visible()
    assert page.locator("#inspector-selection").is_hidden()
    assert page.locator("#tab-evaluation").get_attribute("aria-selected") == "true"
    assert page.locator(".inspector-card").bounding_box() == card_bounds
    for key, selected in [
        ("Home", "selection"),
        ("End", "evaluation"),
        ("ArrowRight", "selection"),
        ("ArrowRight", "evaluation"),
        ("ArrowLeft", "selection"),
        ("ArrowLeft", "evaluation"),
    ]:
        page.keyboard.press(key)
        assert page.locator(f"#tab-{selected}").get_attribute("aria-selected") == "true"
        assert page.locator(f"#tab-{selected}").get_attribute("tabindex") == "0"
        assert page.locator(f"#inspector-{selected}").is_visible()
    if width <= 1000:
        page.locator("#workspace-map").click()
    assert page.evaluate("elements.globe.getBoundingClientRect().toJSON()") == map_bounds
    assert page.evaluate("JSON.stringify(state.currentPayload)") == original
    assert_single_screen(page)


@pytest.mark.parametrize(
    ("width", "height"),
    [(1920, 1080), (1440, 900), (1280, 720), (1024, 768), (800, 600), (390, 844), (375, 667)],
)
def test_live_utc_clock_keeps_its_original_size_and_is_read_only_below_the_brand(
    page: Any, lab_url: str, width: int, height: int
) -> None:
    page.set_viewport_size({"width": width, "height": height})
    reference_ready(page, lab_url)
    page.evaluate("document.fonts.ready")
    original = page.evaluate("JSON.stringify(state.referenceData)")
    map_bounds = page.evaluate("elements.globe.getBoundingClientRect().toJSON()")
    clock = page.locator("#replay-time")
    assert clock.is_visible()
    assert page.locator("#replay-time").count() == 1
    assert page.locator(".replay-bar time").count() == 0
    assert page.locator("#replay-time-button, #replay-time-picker, #replay-utc-input").count() == 0
    assert page.locator("#replay-time").inner_text() == "2025-11-18 12:00:00 UTC"
    assert clock.evaluate("""node => {
      const header = node.closest('.masthead'), box = header.getBoundingClientRect();
      const title = header.querySelector('.brand > span').getBoundingClientRect();
      const time = node.getBoundingClientRect(), style=getComputedStyle(node);
      return box.height === 56 && time.top >= title.bottom - 1
        && Math.abs(time.left - title.left) < 1 && time.bottom <= box.bottom
        && header.scrollWidth <= header.clientWidth && node.tagName==='TIME'
        && !node.closest('button,a') && node.tabIndex===-1
        && style.fontSize==='10px' && style.lineHeight==='16px'
        && style.fontWeight==='500' && style.cursor!=='pointer';
    }""")
    page.evaluate("() => {setReplayTime(3600, true);}")
    assert page.locator("#replay-time").inner_text() == "2025-11-18 13:00:00 UTC"
    clock.click()
    assert page.evaluate("state.replay.time === 3600 && !state.replay.playing")
    assert clock.get_attribute("datetime") == "2025-11-18T13:00:00.000Z"
    assert "Click" not in clock.get_attribute("title")
    page.locator("#replay-play").click()
    page.wait_for_function("state.replay.time > 3601")
    clock.click()
    assert page.evaluate("state.replay.playing && state.replay.time > 3601")
    page.evaluate("setReplayTime(3600,true)")
    if width <= 1000:
        for view in ["tasks", "summary", "map"]:
            page.locator(f"#workspace-{view}").click()
            assert clock.is_visible()
            clock.click()
            assert page.evaluate("state.replay.time === 3600 && !state.replay.playing")
    clock.click()
    page.locator("#status").click()
    assert page.locator("#replay-time-picker").count() == 0
    assert page.evaluate("elements.globe.getBoundingClientRect().toJSON()") == map_bounds
    assert page.evaluate("JSON.stringify(state.referenceData)") == original
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
    page.locator('.target-row[data-task-id="M350"]').click()
    assert page.locator("#selected-state").text_content() == "Observing"
    assert "12:00:00 UTC" in page.locator("#replay-time").inner_text()
    page.locator("#replay-scrub").evaluate(
        "node => {node.value = 7.9; node.dispatchEvent(new Event('input'));}"
    )
    assert page.locator("#selected-state").text_content() == "Observing"
    assert page.locator('.map-ray[data-task-id="M350"]').count() == 0
    assert page.locator("#toggle-rays").count() == 0
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


def test_playback_windows_extend_without_executing_tasks(page: Any, lab_url: str) -> None:
    reference_ready(page, lab_url)
    initial = page.evaluate("JSON.stringify(state.currentPayload)")
    page.locator("#replay-window-prev").click()
    assert page.evaluate("state.replay.time") == -43200
    assert page.locator("#orbit-basis").is_visible()
    assert page.locator("#mission-globe").get_attribute("data-orbit-basis") == "estimated"
    assert page.locator("#replay-time").inner_text() == "2025-11-18 00:00:00 UTC"
    assert page.locator(".map-ray").count() == 0
    assert page.locator("#selected-state").inner_text() == "Planned"
    assert page.locator(".map-track-past").count() >= 20
    assert page.locator(".map-track-future").count() >= 20
    for _ in range(7):
        page.locator("#replay-window-next").click()
    assert page.evaluate("state.replay.time") == 3 * 86400
    assert page.locator("#replay-time").inner_text() == "2025-11-21 12:00:00 UTC"
    assert page.locator("#selected-state").inner_text() == "Completed"
    assert page.locator(".map-ray").count() == 0
    assert page.locator(".time-cursor").is_hidden()
    assert page.locator("#replay-time-picker").count() == 0
    assert page.evaluate("JSON.stringify(state.currentPayload)") == initial
    page.locator("#replay-reset").click()
    assert page.evaluate("[state.replay.time,state.replay.windowStart,state.replay.windowEnd]") == [
        0,
        0,
        43200,
    ]
    assert page.locator("#orbit-basis").is_hidden()
    assert page.locator("#selected-state").inner_text() == "Observing"
    assert_single_screen(page)


def test_playback_continues_across_both_source_boundaries(page: Any, lab_url: str) -> None:
    reference_ready(page, lab_url)
    page.locator("#replay-speed").select_option("900")
    page.evaluate("setReplayTime(43199.9, true)")
    page.locator("#replay-play").click()
    page.wait_for_function("state.replay.time > 43300 && state.replay.playing")
    page.locator("#replay-play").click()
    assert page.locator("#orbit-basis").is_visible()
    assert page.locator(".map-ray").count() == 0
    page.evaluate("setReplayTime(.1, true)")
    page.locator("#replay-direction").click()
    assert page.locator("#replay-direction").get_attribute("aria-pressed") == "true"
    page.locator("#replay-play").click()
    page.wait_for_function("state.replay.time < -100 && state.replay.playing")
    page.locator("#replay-play").click()
    assert page.locator("#orbit-basis").is_visible()
    assert page.locator(".map-ray").count() == 0
    assert page.evaluate("state.currentPayload.result.metrics.completed_tasks") == 488
    assert_single_screen(page)


@pytest.mark.parametrize(("width", "height"), [(1440, 900), (800, 600), (375, 667)])
def test_extended_playback_controls_and_read_only_clock_fit_without_scroll(
    page: Any, lab_url: str, width: int, height: int
) -> None:
    page.set_viewport_size({"width": width, "height": height})
    reference_ready(page, lab_url)
    page.locator("#replay-window-next").click()
    page.locator("#replay-time").click()
    assert page.locator("#replay-time-picker, #replay-utc-input").count() == 0
    assert page.evaluate("state.replay.time === 43200 && !state.replay.playing")
    bounds = page.locator("#replay-time").bounding_box()
    assert 0 <= bounds["x"] <= width - bounds["width"]
    assert 0 <= bounds["y"] <= height - bounds["height"]
    assert_single_screen(page)


def test_invalid_time_does_not_corrupt_the_clock_or_start_a_local_solve(
    page: Any, lab_url: str
) -> None:
    reference_ready(page, lab_url)
    assert not page.evaluate("setReplayTime(NaN, true)")
    assert page.evaluate("state.replay.time") == 0
    assert page.locator("#status").get_attribute("class") == "status error"
    assert page.evaluate("setReplayTime(-86400, true)")
    assert page.locator("#status").get_attribute("class") == "status"


@pytest.mark.parametrize(
    ("width", "height"),
    [(1920, 1080), (1440, 900), (1280, 720), (1024, 768), (800, 600), (390, 844), (375, 667)],
)
def test_timeline_filter_shares_its_heading_and_all_lanes_scroll_without_page_controls(
    page: Any, lab_url: str, width: int, height: int
) -> None:
    page.set_viewport_size({"width": width, "height": height})
    reference_ready(page, lab_url)
    map_bounds = page.locator("#mission-globe").bounding_box()
    timeline = page.locator("#timeline-chart")
    assert (
        page.locator("#timeline-title, #timeline-prev, #timeline-next, #timeline-range").count()
        == 0
    )
    assert page.locator("#pane-timeline .visual-heading, #pane-timeline .pager").count() == 0
    assert (
        page.locator(
            "#inspector-selection .selection-details dt", has_text="Observation · UTC"
        ).count()
        == 1
    )
    assert page.locator("#pane-timeline").get_by_text("Observation · UTC", exact=True).count() == 0
    assert page.locator("#satellite-filter").evaluate("""node => {
      const header = node.closest('.dock-header');
      const title = header.querySelector('#schedule-title').getBoundingClientRect();
      const legend = header.querySelector('.timeline-legend').getBoundingClientRect();
      const select = node.getBoundingClientRect(), bounds = header.getBoundingClientRect();
      return legend.left > title.right && select.left > legend.right
        && bounds.right - select.right <= 14
        && Math.abs((legend.top+legend.bottom-select.top-select.bottom)/2) < 1
        && select.top >= bounds.top && select.bottom <= bounds.bottom
        && Math.abs((title.top+title.bottom-select.top-select.bottom)/2) < 1
        && header.scrollWidth <= header.clientWidth;
    }""")
    assert page.locator(".satellite-lane").count() == 20
    assert page.locator(".task-bar").count() == 488
    assert timeline.evaluate("node => node.scrollHeight > node.clientHeight + 200")
    assert_timeline_playback_alignment(page)
    assert page.locator(".timeline-scale text").all_text_contents() == [
        "12:00",
        "15:00",
        "18:00",
        "21:00",
        "00:00",
    ]
    assert timeline.evaluate("""node => {
      const lines = [...node.querySelectorAll('.timeline-lanes > .chart-grid')];
      return [...node.querySelectorAll('.timeline-scale text')].every((text, i) => {
        const point = text.ownerSVGElement.createSVGPoint();
        point.x = Number(text.getAttribute('x'));
        const label = point.matrixTransform(text.getScreenCTM());
        return Math.abs(label.x - lines[i].getBoundingClientRect().x) < 1;
      });
    }""")
    box = timeline.bounding_box()
    page.mouse.move(box["x"] + box["width"] - 15, box["y"] + box["height"] / 2)
    page.mouse.wheel(0, 1000)
    page.wait_for_function("elements.timeline.scrollTop > 200")
    assert timeline.evaluate("""node => {
      const box = node.getBoundingClientRect();
      const axis = node.querySelector('.timeline-scale').getBoundingClientRect();
      const last = node.querySelector('.satellite-lane:last-of-type').getBoundingClientRect();
      return Math.abs(axis.top - box.top) < 1 && axis.bottom < box.bottom
        && last.top >= axis.bottom - 1 && last.bottom <= box.bottom + 1
        && node.scrollWidth <= node.clientWidth;
    }""")
    timeline.focus()
    timeline.press("Home")
    page.wait_for_function("elements.timeline.scrollTop === 0")
    timeline.press("End")
    page.wait_for_function("elements.timeline.scrollTop > 200")
    end = timeline.evaluate("node => node.scrollTop")
    timeline.press("PageUp")
    assert timeline.evaluate("node => node.scrollTop") < end
    timeline.press("Home")
    timeline.press("ArrowDown")
    assert timeline.evaluate("node => node.scrollTop") == 34
    timeline.press("ArrowUp")
    assert timeline.evaluate("node => node.scrollTop") == 0
    assert page.locator("#mission-globe").bounding_box() == map_bounds
    assert_single_screen(page)


@pytest.mark.parametrize(("width", "height"), [(1440, 900), (1024, 768), (800, 600), (375, 667)])
def test_timeline_scrubber_matches_ticks_and_preserves_focus_in_extended_playback(
    page: Any, lab_url: str, width: int, height: int
) -> None:
    page.set_viewport_size({"width": width, "height": height})
    reference_ready(page, lab_url)
    source = page.evaluate("JSON.stringify(state.currentPayload)")
    slider = page.locator("#replay-scrub")
    assert_timeline_playback_alignment(page)
    for time in [10800, 21600, 32400]:
        slider.evaluate(
            "(node, time) => {node.value=time; node.dispatchEvent(new Event('input'));}", time
        )
        assert page.evaluate("state.replay.time") == time
        assert_timeline_playback_alignment(page)
    slider.focus()
    page.evaluate(
        "() => {window.originalScrubber = document.getElementById('replay-scrub');refreshPanels();}"
    )
    assert slider.evaluate("node => node === originalScrubber && node === document.activeElement")
    bounds = slider.bounding_box()
    page.mouse.click(
        bounds["x"] + 5 + (bounds["width"] - 10) / 2, bounds["y"] + bounds["height"] / 2
    )
    assert abs(page.evaluate("state.replay.time") - 21600) <= 43200 / (bounds["width"] - 10)
    assert_timeline_playback_alignment(page)
    page.evaluate("() => {setReplayTime(21600, true);}")
    page.locator("#replay-window-next").click()
    assert page.evaluate("[state.replay.windowStart,state.replay.windowEnd]") == [43200, 86400]
    assert page.locator(".timeline-axis text").all_text_contents() == [
        "00:00",
        "03:00",
        "06:00",
        "09:00",
        "12:00",
    ]
    assert page.locator(".task-bar:not([hidden]), .window-bar, .map-ray").count() == 0
    assert_timeline_playback_alignment(page)
    page.locator("#replay-window-prev").click()
    page.locator("#replay-window-prev").click()
    assert page.evaluate("[state.replay.windowStart,state.replay.windowEnd]") == [-43200, 0]
    assert page.locator(".task-bar:not([hidden]), .window-bar, .map-ray").count() == 0
    assert_timeline_playback_alignment(page)
    slider.focus()
    page.evaluate("() => {setReplayTime(3 * 86400 + 21600, true);}")
    assert slider.evaluate("node => node === originalScrubber && node === document.activeElement")
    assert_timeline_playback_alignment(page)
    page.locator("#replay-reset").click()
    assert page.locator(".task-bar:not([hidden])").count() == 488
    assert page.locator(".timeline-axis text").all_text_contents() == [
        "12:00",
        "15:00",
        "18:00",
        "21:00",
        "00:00",
    ]
    assert_timeline_playback_alignment(page)
    assert page.evaluate("JSON.stringify(state.currentPayload)") == source
    assert_single_screen(page)


@pytest.mark.parametrize(("width", "height"), [(1440, 900), (1024, 768), (800, 600), (375, 667)])
def test_timeline_scroll_focus_filters_and_task_link_survive_replay_and_plan_switch(
    page: Any, lab_url: str, width: int, height: int
) -> None:
    page.set_viewport_size({"width": width, "height": height})
    reference_ready(page, lab_url)
    original = page.evaluate("JSON.stringify(state.referenceData)")
    timeline = page.locator("#timeline-chart")
    bar = page.locator(".task-bar").last
    task_id = bar.get_attribute("data-task-id")
    bar.focus()
    top = timeline.evaluate("node => node.scrollTop")
    assert top > 200
    page.evaluate("() => {setReplayTime(3600, true); refreshPanels();}")
    assert timeline.evaluate("node => node.scrollTop") == top
    assert page.locator(f'.task-bar[data-task-id="{task_id}"]').evaluate(
        "node => node === document.activeElement"
    )
    page.set_viewport_size({"width": width, "height": height - 30})
    page.wait_for_timeout(120)
    assert timeline.evaluate("node => node.scrollTop") == top
    assert page.locator(f'.task-bar[data-task-id="{task_id}"]').evaluate(
        "node => node === document.activeElement"
    )
    page.locator("#solver-select").select_option("eos-ppo-profit")
    assert page.locator(".satellite-lane").count() == 20
    assert timeline.evaluate("node => node.scrollTop") == top
    page.locator("#solver-select").select_option("eos-sa-balanced")
    assert timeline.evaluate("node => node.scrollTop") == top
    page.evaluate("() => {selectTarget('M350', true, false);}")
    if width <= 1000:
        page.locator("#workspace-map").click()
    assert timeline.evaluate("""node => {
      const box = node.getBoundingClientRect();
      const axis = node.querySelector('.timeline-scale').getBoundingClientRect();
      const selected = node.querySelector('[data-satellite-id="KENT_RIDGE_1_41167"]')
        .getBoundingClientRect();
      return selected.top >= axis.bottom - 1 && selected.bottom <= box.bottom + 1;
    }""")
    assert page.locator("#selected-window").text_content() == "12:00:00\u201312:00:08"
    page.locator("#satellite-filter").select_option("KENT_RIDGE_1_41167")
    assert page.locator(".satellite-lane").count() == 1
    assert timeline.evaluate("node => node.scrollTop") == 0
    assert timeline.evaluate("node => node.scrollHeight <= node.clientHeight")
    page.locator("#satellite-filter").select_option("all")
    assert page.locator(".satellite-lane").count() == 20
    assert timeline.evaluate("node => node.scrollTop") == 0
    assert page.evaluate("JSON.stringify(state.referenceData)") == original
    assert_single_screen(page)


def test_reference_all_twenty_satellite_lanes_and_plan_switching(page: Any, lab_url: str) -> None:
    reference_ready(page, lab_url)
    satellites = set(
        page.locator(".satellite-lane").evaluate_all(
            "nodes => nodes.map(node => node.dataset.satelliteId)"
        )
    )
    assert len(satellites) == 20
    assert page.locator("#timeline-prev, #timeline-next, #timeline-range").count() == 0
    page.locator("#satellite-filter").select_option("KENT_RIDGE_1_41167")
    assert page.locator(".satellite-lane").count() == 1
    page.locator('#comparison-legend button[data-plan-id="eos-sa-profit"]').click()
    assert page.evaluate("state.currentPayload.evaluation.TP") == 2833
    assert page.evaluate("state.currentPayload.result.metrics.completed_tasks") == 493
    assert page.evaluate("state.currentPayload.result.validation.is_feasible") is None
    assert "Different objectives" in page.locator("#comparison-chart svg desc").text_content()
    assert page.evaluate("state.currentPayload.result.validation.is_feasible") is None
    assert page.locator("#export-run, a[download]").count() == 0
    assert (
        page.evaluate("state.currentPayload.provenance.revision")
        == "ee282656e8b2f6fd0d3cf84677b40966e2780ef3"
    )
    assert_single_screen(page)


def test_fallback_footprints_never_accumulate_history_and_observation_links_are_removed(
    page: Any, lab_url: str
) -> None:
    reference_ready(page, lab_url)
    assert page.locator("#toggle-rays").count() == 0
    for time in [-86400, 0, 3.5, 8, 125.5, 43201, 125.5, 0, -86400]:
        page.evaluate("time => setReplayTime(time,true)", time)
        assert page.locator(".map-fov").count() == 20
        assert page.locator(".map-ray").count() == 0
        assert page.evaluate("""() => [...document.querySelectorAll('.map-fov')].every(node => {
          const id = node.dataset.satelliteId, model = state.orbitModels.get(id);
          const attitude = satelliteFrame(id), time = state.replay.time;
          const frame = SensorFov.frame(model.cartesian(time),attitude?.direction,attitude?.x);
          return frame?.footprint.length ? node.children.length > 0
            : node.children.length === 0 && node.style.display === 'none';
        })""")
    page.evaluate("setReplayTime(0,true); selectSatellite('KENT_RIDGE_1_41167')")
    page.locator("#toggle-layers").click()
    assert page.get_by_role("button", name="Observation links", exact=True).count() == 0
    assert page.locator(".map-ray").count() == 0
    page.evaluate("setReplayTime(8,true)")
    assert page.locator(".map-ray").count() == 0
    page.keyboard.press("Escape")


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
    assert page.evaluate("state.currentPayload.result.metrics.completed_tasks") == 492
    assert page.locator("#replay-scrub").input_value() == "0"
    assert page.locator(".map-satellite").count() == 20
    assert page.locator(".map-marker").count() == 500
    assert page.locator("#pending-state, #run-button").count() == 0
    assert_single_screen(page)


def test_radar_uses_source_values_correct_directions_and_distinct_csp_safe_colours(
    page: Any, lab_url: str
) -> None:
    reference_ready(page, lab_url)
    original = page.evaluate("JSON.stringify(state.referenceData)")
    assert page.locator("#comparison-chart .radar-series").count() == 7
    assert page.locator("#comparison-chart .radar-point").count() == 35
    assert page.locator("#comparison-chart .radar-axis").evaluate_all(
        "nodes => nodes.map(n => n.firstChild.textContent)"
    ) == ["TP ↑", "TCR ↑", "TM ↓", "RT ↓", "BD ↑"]
    series = page.locator(".radar-series").evaluate_all("""nodes => nodes.map(n => ({
      id:n.dataset.planId, colour:getComputedStyle(n).color,
      stroke:getComputedStyle(n.querySelector('polygon')).stroke,
      dashes:n.querySelector('polygon').getAttribute('stroke-dasharray'),
      points:[...n.querySelectorAll('circle')].map(p => ({key:p.dataset.metric,
        raw:Number(p.dataset.raw), score:Number(p.dataset.score)}))
    }))""")
    assert len({item["colour"] for item in series}) == 7
    assert len({item["dashes"] for item in series}) == 7
    for item in series:
        assert item["colour"] == item["stroke"], item
        expected = page.evaluate(
            "id => {const p = state.referenceData.plans.find(p => p.plan_id === id);"
            "return {...p.recomputed_metrics, RT:p.source_metrics.RT};}",
            item["id"],
        )
        for point in item["points"]:
            assert point["raw"] == expected[point["key"]]
            assert 0 <= point["score"] <= 1
        tm = next(point for point in item["points"] if point["key"] == "TM")
        assert tm["score"] == pytest.approx(1 - expected["TM"])
    assert page.locator("#comparison-values dd").all_text_contents() == [
        "2816",
        "97.6%",
        "0.307",
        "87.4s",
        "0.674",
    ]
    assert page.locator("#comparison-info, #comparison-scales").count() == 0
    assert "no overall ranking" in page.locator("#comparison-chart svg desc").text_content()
    assert page.evaluate("JSON.stringify(state.referenceData)") == original


def test_precise_orbit_chunks_and_scoped_checks_survive_plan_switch_and_time_jumps(
    page: Any,
    lab_url: str,
) -> None:
    reference_ready(page, lab_url)
    original = page.evaluate("JSON.stringify(state.referenceData)")
    assert page.locator("#mission-globe").get_attribute("data-orbit-precision") == "1s"
    for plan, count in [("eos-mip-profit", 355), ("eos-ga-profit", 488), ("eos-aco-profit", 488)]:
        page.locator("#solver-select").select_option(plan)
        page.wait_for_function(
            "id => !state.busy && state.currentPayload.reference_plan.plan_id === id", arg=plan
        )
        assert page.evaluate("state.assignments.size") == count
        page.locator("#tab-evaluation").click()
        assert page.locator("#metric-budget").inner_text() == "pass"
        assert "gaps" in page.locator("#metric-transitions").inner_text()
        assert "/" in page.locator("#metric-occlusion").inner_text()
        assert page.locator("#metric-occlusion").is_visible()
        assert_single_screen(page)
    for time in [3599.5, 3600, 3600.5, 22000, -86400, 43199, 43200, 86400]:
        page.evaluate("t => {setReplayTime(t,true);}", time)
        page.wait_for_function("state.ephemeris.pendingCount === 0")
        if 0 <= time <= 43200:
            page.wait_for_function("elements.globe.dataset.orbitPrecision === '1s'")
        else:
            assert (
                page.locator("#mission-globe").get_attribute("data-orbit-precision") == "estimated"
            )
            assert page.locator(".map-ray").count() == 0
        assert page.evaluate("state.ephemeris.cacheSize") <= 4
    assert page.evaluate("JSON.stringify(state.referenceData)") == original


def test_failed_dense_ephemeris_is_reported_as_preview_and_pauses_playback(
    page: Any,
    lab_url: str,
) -> None:
    page.route("**/orbit-data/**", lambda route: route.fulfill(status=503, body="unavailable"))
    reference_ready(page, lab_url)
    assert "30 s preview" in page.locator("#status").inner_text()
    assert page.locator("#mission-globe").get_attribute("data-orbit-precision") == "preview-30s"
    assert page.evaluate("state.ephemeris.cacheSize") == 0
    assert page.evaluate("state.replay.playing") is False
    assert page.locator(".map-satellite").count() == 20


@pytest.mark.parametrize(
    ("width", "height"), [(1920, 1080), (1440, 900), (1024, 768), (800, 600), (375, 667)]
)
def test_refined_chart_depth_keeps_exact_metric_geometry_and_coordinated_controls(
    page: Any, lab_url: str, width: int, height: int
) -> None:
    page.set_viewport_size({"width": width, "height": height})
    reference_ready(page, lab_url)
    source = page.evaluate("JSON.stringify(state.referenceData)")
    if width <= 1000:
        page.locator("#workspace-summary").click()
    assert page.locator(".radar-point-halo").count() == 5
    assert page.locator(".radar-reference-ring[aria-hidden=true]").count() == 1
    assert (
        page.locator(".radar-plinth[aria-hidden=true], .radar-surface[aria-hidden=true]").count()
        == 2
    )
    assert page.locator(".radar-series").evaluate_all("""nodes => nodes.every(node => {
      const area = node.querySelector('.radar-area');
      const points = [...area.points];
      return !area.hasAttribute('transform') && [...node.querySelectorAll('.radar-point')]
        .every((point, index) => Math.abs(points[index].x - Number(point.getAttribute('cx'))) < 1e-4
          && Math.abs(points[index].y - Number(point.getAttribute('cy'))) < 1e-4)
        && getComputedStyle(area).fill.includes('radar-fill-');
    })""")
    assert page.locator("#comparison-chart #radar-depth feDropShadow").count() == 1
    assert_single_screen(page)
    if width <= 1000:
        page.locator("#workspace-tasks").click()
    assert page.locator(".workload-row").evaluate_all("""nodes => {
      const plan = state.currentPayload.reference_plan;
      const maximum = Math.max(1, ...Object.values(plan.workloads));
      return nodes.every(node => {
        const bar = node.querySelector('.workload-bar');
        const track = node.querySelector('.workload-track');
        return Math.abs(Number(bar.getAttribute('width')) / Number(track.getAttribute('width'))
          - plan.workloads[node.dataset.satelliteId] / maximum) < 1e-12
          && bar.getAttribute('x') === track.getAttribute('x')
          && bar.getAttribute('height') === track.getAttribute('height')
          && bar.getAttribute('height') === '8'
          && getComputedStyle(bar).fill.includes('workload-');
      });
    }""")
    assert page.locator("#resource-chart #workload-depth feDropShadow").count() == 1
    assert page.locator(".workload-unit").count() == page.locator(".workload-row").count()
    assert page.locator(".workload-selection-marker[aria-hidden=true]").count() == 0
    page.locator(".workload-row").first.click()
    assert page.locator(".workload-selection-marker[aria-hidden=true]").count() == 1
    assert_single_screen(page)
    if width <= 1000:
        page.locator("#workspace-map").click()
    assert page.evaluate("""() => {
      const cards = [...document.querySelectorAll('.command-card')];
      const instruments = [...document.querySelectorAll(
        '#target-filter, #satellite-filter, .inspector-tabs')]
        .map(node => getComputedStyle(node));
      const mapControls = [...document.querySelectorAll(
        '.algorithm-control select, .viewport-tools, .map-projections, .replay-controls')]
        .map(node => getComputedStyle(node));
      return cards.every(node => getComputedStyle(node).borderRadius === '8px'
        && getComputedStyle(node).boxShadow !== 'none')
        && instruments.every(style => style.borderRadius === '5px'
          && style.backgroundImage === instruments[0].backgroundImage)
        && mapControls.every(style => style.borderRadius === '5px'
          && style.backgroundImage === mapControls[0].backgroundImage);
    }""")
    assert page.evaluate("""() => {
      const snapshot = () => [...document.querySelectorAll(
        '.globe-card, .viewport-toolbar, .viewport-tools, .map-projections, '
        + '.globe-frame, .globe-overlay, .viewport-compass, .replay-bar, .replay-controls')]
        .map(node => {
          const style = getComputedStyle(node), box = node.getBoundingClientRect();
          return [style.backgroundColor, style.backgroundImage, style.borderRadius,
            style.borderColor, style.boxShadow, style.color, style.fontFamily,
            style.fontSize, box.x, box.y, box.width, box.height];
        });
      const panels = [...document.querySelectorAll('.console-panel')];
      const styled = JSON.stringify(snapshot());
      panels.forEach(node => node.classList.remove('console-panel'));
      const plain = JSON.stringify(snapshot());
      panels.forEach(node => node.classList.add('console-panel'));
      return panels.length === 5 && styled === plain
        && !document.querySelector('.globe-card .console-panel');
    }""")
    assert_timeline_playback_alignment(page)
    page.locator("#solver-select").select_option("eos-ppo-profit")
    assert page.locator(".radar-point-halo").count() == 5
    assert page.locator("#timeline-chart linearGradient").count() == 5
    assert page.locator(".resource-readouts, #comparison-info, #timeline-title").count() == 0
    assert page.evaluate("JSON.stringify(state.referenceData)") == source
    assert_single_screen(page)


@pytest.mark.parametrize(("width", "height"), [(1440, 900), (800, 600), (375, 667)])
def test_header_algorithm_switch_is_immediate_and_keeps_the_workspace_view(
    page: Any, lab_url: str, width: int, height: int
) -> None:
    page.set_viewport_size({"width": width, "height": height})
    requests: list[str] = []
    page.on(
        "request", lambda request: requests.append(request.url) if "/api/" in request.url else None
    )
    reference_ready(page, lab_url)
    select = page.get_by_label("Optimization Algorithm", exact=True)
    assert select.evaluate("n => Boolean(n.closest('.header-actions'))")
    assert page.get_by_text("Optimization Algorithm", exact=True).count() == 0
    assert page.locator(".algorithm-control label").count() == 0
    assert select.evaluate("""n => {
      const select = n.getBoundingClientRect();
      const header = document.querySelector('.masthead').getBoundingClientRect();
      return Math.abs((select.top + select.bottom) / 2 - (header.top + header.bottom) / 2) < 1;
    }""")
    assert page.locator("#run-button, #solve-form, #pending-state, #tab-comparison").count() == 0
    if width <= 1000:
        page.locator("#workspace-tasks").click()
    assert page.get_by_role("heading", name="Task List", exact=True).count() == 1
    before = page.evaluate("elements.globe.getBoundingClientRect().toJSON()")
    original = page.evaluate("JSON.stringify(state.referenceData)")
    for plan in ["eos-sa-profit", "eos-greedy-profit", "eos-ppo-profit", "eos-sa-balanced"]:
        select.select_option(plan)
        assert page.evaluate("state.currentPayload.reference_plan.plan_id") == plan
        assert (
            page.locator("#comparison-legend button[aria-pressed=true]").get_attribute(
                "data-plan-id"
            )
            == plan
        )
        assert page.locator(".radar-series").last.get_attribute("data-plan-id") == plan
        assert page.evaluate("state.replay.time") == 0
        assert page.locator("#comparison-chart").is_visible() == (width > 1000)
        assert page.locator("#resource-chart, #target-list").evaluate_all(
            "nodes => nodes.every(node => getComputedStyle(node).visibility === 'visible')"
        )
        assert page.evaluate("elements.globe.getBoundingClientRect().toJSON()") == before
    assert page.evaluate("JSON.stringify(state.referenceData)") == original
    assert requests == [lab_url + "/api/reference/data"]
    if width <= 1000:
        assert page.locator(".shell").get_attribute("data-workspace-view") == "tasks"
    assert_single_screen(page)


def test_task_list_scroll_and_focus_survive_replay_resize_and_plan_switch(
    page: Any, lab_url: str
) -> None:
    reference_ready(page, lab_url)
    assert page.locator(".target-row").count() == 500
    last = page.locator('.target-row[data-task-id="M500"]')
    last.focus()
    last.press("Enter")
    assert page.locator("#selected-id").inner_text() == "M500"
    top = page.locator("#target-list").evaluate("n => n.scrollTop")
    assert top > 20000
    page.evaluate("""() => {window._taskRow = document.activeElement;
      setReplayTime(43200, true); refreshPanels();} """)
    assert last.evaluate("n => n === window._taskRow && n === document.activeElement")
    assert page.locator("#target-list").evaluate("n => n.scrollTop") == top
    page.set_viewport_size({"width": 1440, "height": 860})
    page.wait_for_timeout(100)
    assert last.evaluate("n => n === window._taskRow && n === document.activeElement")
    page.locator("#solver-select").select_option("eos-ppo-profit")
    assert page.locator(".target-row").count() == 500
    assert page.locator("#target-list").evaluate("n => n.scrollTop") > 20000
    page.locator("#target-filter").select_option("active")
    page.evaluate("() => {setReplayTime(43200, true);}")
    assert page.locator("#target-list").inner_text() == "No matching tasks"
    assert page.locator("#target-count").count() == 0
    page.evaluate("selectTarget('M500', true, false)")
    assert page.locator("#target-filter").input_value() == "all"
    assert page.locator("#target-search").count() == 0
    assert page.locator(".target-row").count() == 500
    assert last.get_attribute("aria-pressed") == "true"
    assert last.evaluate("""n => {const r = n.getBoundingClientRect();
      const b = elements.targetList.getBoundingClientRect();
      return r.top >= b.top - 1 && r.bottom <= b.bottom + 1;}""")
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

    dataset = build_dataset(LabApplication(ROOT / "data/eos-bench/reference.json"))
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
    assert page.evaluate("state.currentPayload.result.metrics.completed_tasks") == 492
    assert not requests
    assert_single_screen(page)


@pytest.mark.parametrize("time", [0, 0.1, 14400, 43199.9, 43200])
def test_reference_orbit_windows_are_centered_and_extend_beyond_source_boundaries(
    page: Any, lab_url: str, time: float
) -> None:
    reference_ready(page, lab_url)
    page.evaluate("time => setReplayTime(time, true)", time)
    windows = page.evaluate("""() => state.currentPayload.replay.orbits.map(orbit => ({
      ...windowForOrbit(orbit), period: orbit.period_s,
      segments: OrbitReplay.trackSegments(
        state.orbitModels.get(orbit.satellite_id).trackSamples(windowForOrbit(orbit).start,
          windowForOrbit(orbit).end), windowForOrbit(orbit).start, windowForOrbit(orbit).end)
    }))""")
    assert len(windows) == 20
    for bounds in windows:
        assert bounds["start"] == pytest.approx(time - bounds["period"] / 2)
        assert bounds["end"] == pytest.approx(time + bounds["period"] / 2)
        assert bounds["past"] + bounds["future"] == pytest.approx(bounds["period"])
        assert bounds["segments"]
    assert page.locator(".map-orbit polyline").count() >= 20
    assert page.locator(".map-track-past").count() >= 20
    assert page.locator(".map-track-future").count() >= 20
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
    assert page.locator("#orbit-hud").is_hidden()
    assert page.locator(".globe-frame #orbit-hud").count() == 1
    assert page.locator(".viewport-tools .orbit-camera").count() == 1
    assert page.evaluate("""() => {
      const frame = document.querySelector('.globe-frame').getBoundingClientRect();
      const controls = document.querySelector('.orbit-camera').getBoundingClientRect();
      const playback = document.querySelector('.replay-bar').getBoundingClientRect();
      return controls.bottom <= frame.top && Math.abs(frame.bottom - playback.top) < 1;
    }""")
    assert page.locator("#camera-focus").count() == 0
    assert page.locator("#camera-follow").is_enabled()
    assert page.locator("#view-2d").get_attribute("aria-pressed") == "true"
    assert page.locator(".map-projections button:disabled").count() == 3
    marker = page.locator('.map-satellite[data-satellite-id="ALOS-2_39766"]')
    marker.focus()
    marker.press("Enter")
    assert page.locator("#orbit-hud").is_visible()
    map_height = page.locator("#mission-globe").bounding_box()["height"]
    page.locator("#close-satellite-details").click()
    assert page.locator("#orbit-hud").is_hidden()
    assert page.locator("#mission-globe").bounding_box()["height"] == map_height
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


def assert_compact_satellite_details(page: Any) -> None:
    snapshot = page.locator("#orbit-hud").evaluate("""node => {
      const style=getComputedStyle(node),box=node.getBoundingClientRect();
      const map=elements.globe.getBoundingClientRect();
      const telemetry=getComputedStyle(node.querySelector('.orbit-telemetry'));
      return {width:box.width,height:box.height,mapWidth:map.width,
        alpha:Number(style.backgroundColor.match(/[0-9.]+/g).at(-1)),
        blur:style.backdropFilter,opacity:style.opacity,
        gap:parseFloat(telemetry.gap),margin:parseFloat(telemetry.marginTop),
        valueOpacity:getComputedStyle(node.querySelector('#satellite-altitude')).opacity,
        valueSize:parseFloat(getComputedStyle(node.querySelector('#satellite-altitude')).fontSize),
        overflow:node.scrollWidth>node.clientWidth || node.scrollHeight>node.clientHeight,
        inside:box.top>=map.top && box.bottom<=map.bottom
          && box.left>=map.left && box.right<=map.right,
        fields:['satellite-altitude','satellite-period','satellite-latitude','satellite-longitude',
          'satellite-position-x','satellite-position-y','satellite-position-z'].every(id=>{
            const field=document.getElementById(id),rect=field.getBoundingClientRect();
            return field.textContent.length>1 && rect.width>0 && rect.left>=box.left
              && rect.right<=box.right && rect.top>=box.top && rect.bottom<=box.bottom;
          })};
    }""")
    assert snapshot["width"] == pytest.approx(min(196, snapshot["mapWidth"] / 2 - 32))
    assert snapshot["height"] <= 180
    assert snapshot["alpha"] == pytest.approx(0.55, abs=0.01)
    assert snapshot["opacity"] == snapshot["valueOpacity"] == "1"
    assert snapshot["blur"] == "blur(6px)"
    assert snapshot["gap"] <= 10 and snapshot["margin"] <= 4
    assert snapshot["valueSize"] >= 11
    assert not snapshot["overflow"]
    assert snapshot["inside"] and snapshot["fields"]


@pytest.mark.parametrize("viewport", [(1440, 900), (800, 600), (375, 667)])
def test_satellite_popup_is_compact_and_transparent_without_hiding_data(
    page: Any, lab_url: str, viewport: tuple[int, int]
) -> None:
    page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
    reference_ready(page, lab_url)
    original = page.evaluate("JSON.stringify(state.currentPayload)")
    page.evaluate("selectSatellite('KENT_RIDGE_1_41167')")
    assert_compact_satellite_details(page)
    assert page.evaluate("JSON.stringify(state.currentPayload)") == original
    assert_single_screen(page)


@pytest.mark.parametrize("viewport", [(1440, 900), (1024, 768), (800, 600), (375, 667)])
def test_map_status_indicators_have_no_panel_surface(
    page: Any, lab_url: str, viewport: tuple[int, int]
) -> None:
    page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
    reference_ready(page, lab_url)
    assert page.locator(".globe-overlay > span").all_text_contents() == [
        "Planned",
        "Observing",
        "Completed",
        "Unassigned",
    ]
    assert page.locator(".globe-overlay i").count() == 4
    assert page.locator(".globe-overlay").evaluate("""node => {
      const s=getComputedStyle(node), box=node.getBoundingClientRect();
      const map=elements.globe.getBoundingClientRect();
      return s.backgroundColor==='rgba(0, 0, 0, 0)' && s.backgroundImage==='none'
        && s.borderTopWidth==='0px' && s.borderRightWidth==='0px'
        && s.borderBottomWidth==='0px' && s.borderLeftWidth==='0px'
        && s.boxShadow==='none' && s.backdropFilter==='none'
        && s.paddingTop==='0px' && s.paddingRight==='0px'
        && s.paddingBottom==='0px' && s.paddingLeft==='0px'
        && s.pointerEvents==='none' && s.textShadow!=='none'
        && box.left>=map.left && box.right<=map.right
        && box.top>=map.top && box.bottom<=map.bottom;
    }""")
    assert_single_screen(page)


@pytest.mark.parametrize("selection", ["initial", "planned", "unassigned", "satellite"])
def test_offline_follow_resolves_a_satellite_without_requiring_a_prior_satellite_pick(
    page: Any, lab_url: str, selection: str
) -> None:
    reference_ready(page, lab_url)
    source = page.evaluate("JSON.stringify(state.currentPayload)")
    if selection in {"planned", "unassigned"}:
        task_id = page.evaluate(
            """planned=>state.currentPayload.scenario.tasks.find(task=>
              state.assignments.has(task.task_id)===planned).task_id""",
            selection == "planned",
        )
        page.locator(f'.target-row[data-task-id="{task_id}"]').evaluate("node=>node.click()")
        assert page.evaluate("state.selectedSatelliteId") is None
    elif selection == "satellite":
        page.locator(".workload-row").first.click()
    expected = page.evaluate("""() => state.selectedSatelliteId
      || state.assignments.get(state.selectedTaskId)?.satellite_id
      || state.currentPayload.replay.orbits[0].satellite_id""")
    task = page.evaluate("state.selectedTaskId")
    time = page.evaluate("state.replay.time")
    follow = page.locator("#camera-follow")
    assert follow.is_enabled()
    follow.click()
    assert page.evaluate("state.cameraMode") == "follow"
    assert page.evaluate("state.selectedSatelliteId") == expected
    assert page.evaluate("state.selectedTaskId") == task
    assert page.evaluate("state.replay.time") == time
    assert (
        page.locator(".workload-row[aria-pressed=true]").get_attribute("data-satellite-id")
        == expected
    )
    assert follow.get_attribute("aria-pressed") == "true"
    follow.click()
    assert page.evaluate("state.cameraMode") == "manual"
    assert follow.is_enabled() and follow.get_attribute("aria-pressed") == "false"
    assert page.evaluate("JSON.stringify(state.currentPayload)") == source
    assert_single_screen(page)


@pytest.mark.parametrize("viewport", [(1440, 900), (375, 667)])
def test_offline_satellite_details_keep_live_geodetic_and_ecef_coordinates(
    page: Any, lab_url: str, viewport: tuple[int, int]
) -> None:
    page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
    reference_ready(page, lab_url)
    page.evaluate("selectSatellite('KENT_RIDGE_1_41167')")
    original = page.evaluate("JSON.stringify(state.currentPayload)")
    for time in [-86400, 0, 3.5, 3600, 43200, 3 * 86400, 0]:
        snapshot = page.evaluate(
            """time => {
          setReplayTime(time,true);
          const p=state.orbitModels.get(state.selectedSatelliteId).cartesian(time);
          const geo=OrbitModel.toGeodetic(p),text=id=>document.getElementById(id).textContent;
          return {xyz:['x','y','z'].map(axis=>Number(text('satellite-position-'+axis))),
            expected:p.map(v=>v/1000),latitude:Number(text('satellite-latitude').slice(0,-1)),
            longitude:Number(text('satellite-longitude').slice(0,-1)),
            expectedLatitude:geo[1],expectedLongitude:geo[0]};
        }""",
            time,
        )
        assert snapshot["xyz"] == pytest.approx(snapshot["expected"], abs=0.000501), snapshot
        assert snapshot["latitude"] == pytest.approx(snapshot["expectedLatitude"], abs=0.000501)
        assert snapshot["longitude"] == pytest.approx(snapshot["expectedLongitude"], abs=0.000501)
    assert page.evaluate("JSON.stringify(state.currentPayload)") == original
    assert page.locator("#orbit-hud").is_visible()
    assert page.locator("#orbit-hud").evaluate("""node => {
      const box=node.getBoundingClientRect(),map=elements.globe.getBoundingClientRect();
      return node.scrollWidth<=node.clientWidth && node.scrollHeight<=node.clientHeight
        && box.top>=map.top && box.bottom<=map.bottom
        && box.left>=map.left && box.right<=map.right;
    }""")
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
    assert page.locator("#solver-select option").count() == 7
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
    assert page.locator(".target-row").count() == 500
    assert page.locator("#target-next, #target-prev").count() == 0
    task = page.locator(".target-row").last
    task_id = task.get_attribute("data-task-id")
    task.click()
    assert page.locator("#selected-id").inner_text() == task_id
    assert "is-selected" in page.locator(f'.map-marker[data-task-id="{task_id}"]').get_attribute(
        "class"
    )
    page.locator("#tab-selection").focus()
    page.keyboard.press("ArrowRight")
    assert page.locator("#tab-evaluation").get_attribute("aria-selected") == "true"


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
    page.locator("#schedule-title").click()
    assert page.locator("#layer-options").is_hidden()


@pytest.mark.parametrize(("width", "height"), [(1440, 900), (800, 600), (375, 667)])
def test_map_actions_share_one_style_without_download_or_orbit_legend(
    page: Any, lab_url: str, width: int, height: int
) -> None:
    page.set_viewport_size({"width": width, "height": height})
    reference_ready(page, lab_url)
    assert page.locator("#export-run, #orbit-span, .orbit-legend, a[download]").count() == 0
    assert page.locator("#inspector .panel-heading button:not([role=tab])").count() == 0
    rail = page.get_by_role("group", name="Map actions", exact=True)
    assert rail.locator(".map-action").count() == 5
    assert rail.locator(".map-action").evaluate_all("nodes => nodes.map(node => node.id)") == [
        "toggle-layers",
        "reset-view",
        "expand-map",
        "camera-overview",
        "camera-follow",
    ]
    assert rail.locator(".map-action svg[aria-hidden='true']").count() == 5
    assert rail.evaluate("""node => {
      const toolbar = document.querySelector('.viewport-toolbar').getBoundingClientRect();
      const frame = document.querySelector('.globe-frame').getBoundingClientRect();
      const box = node.getBoundingClientRect();
      const styles = [...node.querySelectorAll('.map-action')].map(button => {
        const style = getComputedStyle(button), svg = getComputedStyle(button.querySelector('svg'));
        const bounds = button.getBoundingClientRect();
        return {height:style.height,radius:style.borderRadius,border:style.borderTopWidth,
          iconWidth:svg.width,iconHeight:svg.height,font:style.fontFamily,weight:style.fontWeight,
          inside:bounds.left>=box.left && bounds.right<=box.right
            && bounds.top>=box.top && bounds.bottom<=box.bottom};
      });
      return box.top>=toolbar.top && box.bottom<=toolbar.bottom && box.bottom<=frame.top
        && box.left>=toolbar.left && box.right<=toolbar.right
        && styles.every(style=>JSON.stringify(style)===JSON.stringify(styles[0]))
        && styles[0].border==='0px' && styles[0].iconWidth==='14px' && styles[0].inside;
    }""")
    source = page.evaluate("JSON.stringify(state.currentPayload)")
    page.locator("#toggle-layers").click()
    page.wait_for_function("""() => !document.getElementById('toggle-layers').getAnimations()
      .some(animation => animation.pending || animation.playState === 'running')""")
    assert page.locator("#layer-options").is_visible()
    selected_styles = page.evaluate("""() => {
      const color = value => {
        const rgba = value.match(/[0-9.]+/g).map(Number);
        if (rgba.length === 3) rgba.push(1);
        return rgba;
      };
      const selected = id => {
        const style = getComputedStyle(document.getElementById(id));
        return [color(style.backgroundColor),color(style.color),style.boxShadow];
      };
      return {layers:selected('toggle-layers'),overview:selected('camera-overview')};
    }""")
    assert selected_styles["layers"] == selected_styles["overview"], selected_styles
    page.keyboard.press("Escape")
    before = page.locator("#mission-globe").bounding_box()["height"]
    page.locator("#expand-map").click()
    page.wait_for_function("""() => !document.getElementById('expand-map').getAnimations()
      .some(animation => animation.pending || animation.playState === 'running')""")
    assert page.locator(".analysis-dock").is_hidden()
    assert page.locator("#mission-globe").bounding_box()["height"] > before
    assert page.evaluate("""() => {
      const style = id => {
        const rgba = getComputedStyle(document.getElementById(id)).backgroundColor
          .match(/[0-9.]+/g).map(Number);
        if (rgba.length === 3) rgba.push(1);
        return JSON.stringify(rgba);
      };
      return style('expand-map') === style('camera-overview');
    }""")
    page.locator("#expand-map").click()
    assert page.locator("#mission-globe").bounding_box()["height"] == before
    assert page.evaluate("state.replay.time") == 0
    assert page.evaluate("JSON.stringify(state.currentPayload)") == source
    assert_single_screen(page)


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
    assert page.locator("#run-button").count() == 0
    assert page.locator("#solver-select").is_disabled()
    assert page.locator("#export-run").count() == 0
    assert not any("/api/scenarios" in url or "/api/solve" in url for url in requests)


@pytest.mark.parametrize(
    ("width", "height"),
    [(1920, 1080), (1440, 900), (1280, 720), (800, 600), (375, 667), (375, 600)],
)
def test_workload_lists_all_satellites_and_scrolls_without_moving_the_page(
    page: Any, lab_url: str, width: int, height: int
) -> None:
    page.set_viewport_size({"width": width, "height": height})
    reference_ready(page, lab_url)
    source = page.evaluate("JSON.stringify(state.referenceData)")
    map_bounds = page.evaluate("elements.globe.getBoundingClientRect().toJSON()")
    if width <= 1000:
        page.locator("#workspace-tasks").click()
    host = page.locator("#resource-chart")
    heading = page.locator(".resource-block .section-heading").bounding_box()
    assert page.locator(".workload-row").count() == 20
    assert page.evaluate("""() => {
      const rows = [...elements.resources.querySelectorAll('.workload-row')];
      const satellites = state.currentPayload.scenario.satellites;
      const loads = state.currentPayload.reference_plan.workloads;
      const ids = rows.map(row=>row.dataset.satelliteId);
      return new Set(ids).size === satellites.length
        && satellites.every(s=>ids.includes(s.satellite_id))
        && rows.every((row,index)=>row.querySelector('.workload-value').textContent
          === `${loads[row.dataset.satelliteId]} s`
          && (!index || loads[ids[index-1]] >= loads[row.dataset.satelliteId]))
        && elements.resources.scrollHeight > elements.resources.clientHeight
        && elements.resources.scrollWidth <= elements.resources.clientWidth
        && Math.abs(elements.resources.querySelector('svg').getBoundingClientRect().height
          - (satellites.length * layoutSize('workload-row-height') + 4)) < 1;
    }""")
    host.focus()
    host.press("End")
    page.wait_for_function("elements.resources.scrollTop > 0")
    last = page.locator(".workload-row").last
    assert last.evaluate("""row => {
      const bounds = elements.resources.getBoundingClientRect();
      const box = row.getBoundingClientRect();
      return box.top >= bounds.top - 1 && box.bottom <= bounds.bottom + 1;
    }""")
    assert page.locator(".resource-block .section-heading").bounding_box() == heading
    host.press("Home")
    assert host.evaluate("node => node.scrollTop") == 0
    bounds = host.bounding_box()
    assert bounds is not None
    page.mouse.move(bounds["x"] + bounds["width"] / 2, bounds["y"] + bounds["height"] / 2)
    page.mouse.wheel(0, 240)
    page.wait_for_function("elements.resources.scrollTop > 0")
    assert page.locator(".workload-row").count() == 20
    assert page.evaluate("JSON.stringify(state.referenceData)") == source
    assert page.evaluate("elements.globe.getBoundingClientRect().toJSON()") == map_bounds
    assert_single_screen(page)


@pytest.mark.parametrize(("width", "height"), [(1440, 900), (800, 600), (375, 667)])
def test_workload_scroll_focus_and_selection_survive_replay_resize_and_plan_switch(
    page: Any, lab_url: str, width: int, height: int
) -> None:
    page.set_viewport_size({"width": width, "height": height})
    reference_ready(page, lab_url)
    if width <= 1000:
        page.locator("#workspace-tasks").click()
    source = page.evaluate("JSON.stringify(state.referenceData)")
    host = page.locator("#resource-chart")
    host.focus()
    host.press("End")
    last = page.locator(".workload-row").last
    satellite = last.get_attribute("data-satellite-id")
    last.focus()
    last.press("Enter")
    assert page.evaluate("state.selectedSatelliteId") == satellite
    selected = page.locator(f'.workload-row[data-satellite-id="{satellite}"]')
    top = host.evaluate("node => node.scrollTop")
    assert top > 0
    for time in [1, 1200, 43200, -3600, 0]:
        page.evaluate("time => {setReplayTime(time,true);refreshPanels();}", time)
        assert host.evaluate("node => node.scrollTop") == pytest.approx(top, abs=1)
        assert selected.evaluate("node => node === document.activeElement")
    for plan in ["eos-ppo-profit", "eos-mip-profit", "eos-sa-balanced"]:
        page.locator("#solver-select").select_option(plan)
        page.wait_for_function(
            "id => !state.busy && state.currentPayload.reference_plan.plan_id === id", arg=plan
        )
        assert page.locator(".workload-row").count() == 20
        assert host.evaluate("node => node.scrollTop") == pytest.approx(top, abs=1)
        assert selected.evaluate("node => node === document.activeElement")
        assert selected.get_attribute("aria-pressed") == "true"
        assert page.locator(".workload-bar.is-selected").count() == 1
    page.set_viewport_size({"width": width, "height": height - 24})
    page.wait_for_timeout(150)
    assert host.evaluate("node => node.scrollTop") == pytest.approx(top, abs=1)
    assert selected.evaluate("node => node === document.activeElement")
    assert page.evaluate("JSON.stringify(state.referenceData)") == source
    assert_single_screen(page)


@pytest.mark.parametrize(("width", "height"), [(1440, 900), (375, 667)])
def test_indirect_satellite_selection_reveals_its_workload_without_reordering(
    page: Any, lab_url: str, width: int, height: int
) -> None:
    page.set_viewport_size({"width": width, "height": height})
    reference_ready(page, lab_url)
    if width <= 1000:
        page.locator("#workspace-tasks").click()
    ids = page.locator(".workload-row").evaluate_all(
        "nodes => nodes.map(node => node.dataset.satelliteId)"
    )
    satellite = ids[-1]
    page.evaluate("id => {elements.resources.scrollTop=0;selectSatellite(id);}", satellite)
    assert (
        page.locator(".workload-row").evaluate_all(
            "nodes => nodes.map(node => node.dataset.satelliteId)"
        )
        == ids
    )
    assert page.locator("#resource-chart").evaluate("node => node.scrollTop") > 0
    assert page.locator(f'.workload-row[data-satellite-id="{satellite}"]').evaluate("""row => {
      const bounds = elements.resources.getBoundingClientRect();
      const box = row.getBoundingClientRect();
      return row.getAttribute('aria-pressed') === 'true'
        && box.top >= bounds.top - 1 && box.bottom <= bounds.bottom + 1;
    }""")
    assert page.locator(".map-orbit.is-selected").get_attribute("data-satellite-id") == satellite
    assert_single_screen(page)


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
    assert page.locator(f'.workload-row[data-satellite-id="{satellite}"]').evaluate(
        "node => node === document.activeElement"
    )


@pytest.mark.parametrize(("width", "height"), [(1440, 900), (800, 600), (375, 667)])
@pytest.mark.parametrize("planned", [True, False])
def test_task_list_selection_does_not_select_an_orbit_and_workload_stays_independent(
    page: Any, lab_url: str, width: int, height: int, planned: bool
) -> None:
    page.set_viewport_size({"width": width, "height": height})
    reference_ready(page, lab_url)
    source = page.evaluate("JSON.stringify(state.referenceData)")
    assert page.evaluate("state.selectedSatelliteId") is None
    assert page.locator(".map-orbit.is-selected, .workload-bar.is-selected").count() == 0
    if width <= 1000:
        page.locator("#workspace-tasks").click()
    workload = page.locator(".workload-row").first
    satellite = workload.get_attribute("data-satellite-id")
    workload.click()
    assert page.evaluate("state.selectedSatelliteId") == satellite
    assert page.locator(".map-orbit.is-selected").count() == 1
    assert page.locator(".workload-bar.is-selected").count() == 1
    candidate = page.evaluate(
        """({planned,satellite}) => {
          const assignment=state.currentPayload.reference_plan.assignments.find(a=>
            a.satellite_id!==satellite && a.start_s>0);
          const task=planned?state.taskById.get(assignment.task_id)
            :state.currentPayload.scenario.tasks.find(t=>!state.assignments.has(t.task_id));
          return {id:task.task_id,time:planned?assignment.start_s:state.replay.time,
            satellite:planned?satelliteName(assignment.satellite_id)
              :`${task.visibility_windows.length} candidate windows`};
        }""",
        {"planned": planned, "satellite": satellite},
    )
    if width <= 1000:
        page.locator("#workspace-tasks").click()
    task = page.locator(f'.target-row[data-task-id="{candidate["id"]}"]')
    if planned:
        task.click()
    else:
        task.focus()
        task.press("Enter")
    assert page.evaluate("state.selectedTaskId") == candidate["id"]
    assert page.evaluate("state.selectedSatelliteId") is None
    assert not page.evaluate("state.orbitEmphasis")
    assert page.evaluate("state.replay.time") == candidate["time"]
    assert page.locator("#selected-id").text_content() == candidate["id"]
    assert page.locator("#selected-assignment").text_content() == candidate["satellite"]
    assert page.locator(".target-row.is-selected").get_attribute("data-task-id") == candidate["id"]
    assert page.locator(".map-marker.is-selected").get_attribute("data-task-id") == candidate["id"]
    assert page.locator("#orbit-hud").is_hidden()
    assert (
        page.locator(
            ".map-orbit.is-selected, .map-orbit.is-dimmed, .map-satellite.is-selected, "
            '.workload-bar.is-selected, .workload-row[aria-pressed="true"], '
            ".satellite-lane.is-selected"
        ).count()
        == 0
    )
    if planned:
        bar = page.locator(f'.task-bar[data-task-id="{candidate["id"]}"]')
        assert bar.get_attribute("stroke") == "#fff"
    page.evaluate("setReplayTime(state.replay.time+.5,true);refreshPanels()")
    assert page.evaluate("state.selectedSatelliteId") is None
    page.select_option("#solver-select", "eos-ppo-profit")
    page.wait_for_function(
        "!state.busy && state.currentPayload.reference_plan.plan_id==='eos-ppo-profit'"
    )
    assert page.evaluate("state.selectedTaskId") == candidate["id"]
    assert page.evaluate("state.selectedSatelliteId") is None
    assert page.locator(".map-orbit.is-selected, .workload-bar.is-selected").count() == 0
    if width <= 1000:
        page.locator("#workspace-tasks").click()
    workload = page.locator(".workload-row").first
    satellite = workload.get_attribute("data-satellite-id")
    workload.focus()
    workload.press("Enter")
    assert page.evaluate("state.selectedSatelliteId") == satellite
    assert page.evaluate("state.selectedTaskId") == candidate["id"]
    assert page.locator(".map-orbit.is-selected").get_attribute("data-satellite-id") == satellite
    assert page.locator(".workload-bar.is-selected").count() == 1
    page.evaluate("selectTarget(state.selectedTaskId,false,false)")
    assert page.evaluate("state.selectedSatelliteId") == satellite
    assert page.evaluate("JSON.stringify(state.referenceData)") == source
    assert_single_screen(page)


@pytest.mark.parametrize(("width", "height"), [(1440, 900), (1024, 768), (375, 667)])
def test_brand_and_panel_headers_are_clean_and_workload_values_include_seconds(
    page: Any, lab_url: str, width: int, height: int
) -> None:
    page.set_viewport_size({"width": width, "height": height})
    reference_ready(page, lab_url)
    assert page.title() == "OrbitOps"
    assert page.locator(".brand").inner_text() == "ORBITOPS"
    assert page.locator(".brand small, #target-count, .count-badge").count() == 0
    assert page.locator(".catalog-head").count() == 0
    assert page.locator(".map-satellite .satellite-panel").count() == 20
    assert page.locator(".map-satellite .satellite-antenna").count() == 20
    if width <= 1000:
        page.locator("#workspace-tasks").click()
    assert page.locator(".resource-block .section-heading").inner_text() == "Satellite"
    assert page.locator("#results-title").text_content() == "Task details"
    assert page.locator("#selected-id").evaluate("n=>getComputedStyle(n).fontSize") == "14px"
    assert page.locator(".resource-readouts, #energy-readout, #storage-readout").count() == 0
    values = page.locator(".workload-value").all_text_contents()
    assert values and all(value.endswith(" s") for value in values)
    assert page.locator(".workload-value").evaluate_all("""nodes => nodes.every(n => {
      const box = n.getBoundingClientRect(), parent = n.closest('svg').getBoundingClientRect();
      return box.left >= parent.left && box.right <= parent.right + 1;
    })""")
    assert_single_screen(page)


@pytest.mark.parametrize(("width", "height"), [(1440, 900), (1024, 768), (375, 667)])
def test_local_font_and_readable_typography_fit_all_workspace_views(
    page: Any, lab_url: str, width: int, height: int
) -> None:
    page.set_viewport_size({"width": width, "height": height})
    requests: list[str] = []
    page.on("request", lambda request: requests.append(request.url))
    reference_ready(page, lab_url)
    assert page.evaluate(
        "[...document.fonts].some(f => f.family === 'Inter' && f.status === 'loaded')"
    )
    font_requests = [url for url in requests if ".woff" in url or ".ttf" in url]
    assert font_requests == [lab_url + "/fonts/InterVariable.woff2"]
    if width <= 1000:
        page.locator("#workspace-tasks").click()
    assert (
        page.locator(".target-row-name strong").first.evaluate(
            "n => parseFloat(getComputedStyle(n).fontSize)"
        )
        >= 12
    )
    assert (
        page.locator(".target-row-name small").first.evaluate(
            "n => parseFloat(getComputedStyle(n).fontSize)"
        )
        >= 10
    )
    if width <= 1000:
        page.locator("#workspace-summary").click()
    for tab in ["selection", "evaluation"]:
        page.locator(f"#tab-{tab}").click()
        details = page.locator(f"#inspector-{tab} dd").evaluate_all("""nodes => nodes.map(n => ({
          id:n.id, size:parseFloat(getComputedStyle(n).fontSize),
          width:n.clientWidth, content:n.scrollWidth
        }))""")
        for detail in details:
            assert detail["size"] >= 11, detail
            assert detail["content"] <= detail["width"] + 1, detail
    if width <= 1000:
        page.locator("#workspace-map").click()
    page.locator("#satellite-filter").select_option("KENT_RIDGE_1_41167")
    assert page.locator(".satellite-lane .task-label").text_content() == "KENT RIDGE 1"
    assert page.locator("#satellite-filter option:checked").inner_text() == "KENT RIDGE 1"
    assert_single_screen(page)


@pytest.mark.parametrize(
    ("width", "height"),
    [(1920, 1080), (1440, 900), (1024, 768), (800, 600), (375, 667), (375, 600)],
)
def test_workspace_typography_uses_the_plan_summary_scale(
    page: Any, lab_url: str, width: int, height: int
) -> None:
    page.set_viewport_size({"width": width, "height": height})
    reference_ready(page, lab_url)
    page.evaluate("document.fonts.ready")
    groups = [
        (
            ".panel-heading h2, .section-heading h3, .viewport-title h2, .dock-header h3",
            "13px",
            "600",
        ),
        (
            ".selection-details dt, .metric-details dt, .target-row-name small, "
            ".workload-label, .task-sublabel, .radar-axis, .radar-values dt",
            "11px",
            "400",
        ),
        (
            ".selection-details dd, .metric-details dd, .target-row-name strong, "
            ".workload-value, .radar-values dd, .task-label",
            "12px",
            "500",
        ),
        (
            "#target-filter, #satellite-filter, #solver-select, .inspector-tabs button, "
            ".radar-legend button, .map-projections button, .viewport-tools .map-action",
            "11px",
            "500",
        ),
    ]
    for selector, size, weight in groups:
        styles = page.locator(selector).evaluate_all("""nodes => nodes.map(n => {
          const s=getComputedStyle(n);
          return {text:n.textContent,family:s.fontFamily,size:s.fontSize,
            weight:s.fontWeight,numbers:s.fontVariantNumeric};
        })""")
        assert styles, selector
        for style in styles:
            assert "Inter" in style["family"], style
            assert style["size"] == size and style["weight"] == weight, style
            assert "lining-nums" in style["numbers"], style
            assert "tabular-nums" in style["numbers"], style
    assert page.locator(
        ".target-state, .workload-unit, .chart-axis:not(.workload-label, .workload-value), .status"
    ).evaluate_all("""nodes => nodes.every(n =>
      getComputedStyle(n).fontSize === '10px')""")
    map_bounds = page.locator("#mission-globe").bounding_box()
    for view in ["tasks", "summary", "map"]:
        if width <= 1000:
            page.locator(f"#workspace-{view}").click()
        clipped = page.locator(
            ".panel-heading, .section-heading, .dock-header, .viewport-toolbar"
        ).evaluate_all("""nodes => nodes.filter(n => n.checkVisibility()).flatMap(header => {
          const bounds=header.getBoundingClientRect();
          return [...header.querySelectorAll('h2,h3,button,select,.timeline-legend')]
            .filter(n=>n.checkVisibility()).filter(n=>{
              const box=n.getBoundingClientRect();
              return box.left<bounds.left || box.right>bounds.right
                || box.top<bounds.top || box.bottom>bounds.bottom;
            }).map(n=>n.id||n.textContent);
        })""")
        assert clipped == [], (width, height, view, clipped)
        assert page.locator("#mission-globe").bounding_box() == map_bounds
        assert_single_screen(page)


@pytest.mark.parametrize(
    ("width", "height"),
    [
        (1920, 1080),
        (1440, 900),
        (1280, 720),
        (1024, 768),
        (1440, 600),
        (800, 600),
        (390, 844),
        (375, 667),
        (375, 600),
    ],
)
def test_inspector_labels_and_values_share_one_typographic_scale_without_clipping(
    page: Any, lab_url: str, width: int, height: int
) -> None:
    page.set_viewport_size({"width": width, "height": height})
    reference_ready(page, lab_url)
    if width <= 1000:
        page.locator("#workspace-summary").click()
    map_bounds = page.evaluate("elements.globe.getBoundingClientRect().toJSON()")
    card_bounds = page.locator(".inspector-card").bounding_box()
    source = page.evaluate("JSON.stringify(state.referenceData)")
    for plan in ["eos-sa-balanced", "eos-mip-profit", "eos-ppo-profit"]:
        page.select_option("#solver-select", plan)
        page.wait_for_function(
            "id=>!state.busy && state.currentPayload.reference_plan.plan_id===id", arg=plan
        )
        # Exercise the longest assigned satellite name as well as the normal task.
        page.evaluate("""() => {
          const assignment=state.currentPayload.reference_plan.assignments.reduce((a,b)=>
            satelliteName(a.satellite_id).length>=satelliteName(b.satellite_id).length?a:b);
          selectTarget(assignment.task_id,false,false);
        }""")
        styles: dict[str, dict[str, Any]] = {}
        for view in ["selection", "evaluation"]:
            page.locator(f"#tab-{view}").click()
            details = page.locator(f"#inspector-{view} dl").evaluate("""node => {
              const section=node.closest('[role="tabpanel"]');
              const panel=section.getBoundingClientRect();
              const entries=[...node.querySelectorAll('dt,dd')];
              const font=n=>{
                const s=getComputedStyle(n);
                return {family:s.fontFamily,size:s.fontSize,weight:s.fontWeight,
                  height:s.lineHeight,spacing:s.letterSpacing,numbers:s.fontVariantNumeric,
                  color:s.color,alignment:s.textAlign};
              };
              return {overflow:section.scrollHeight>section.clientHeight+1,
                labels:entries.filter(n=>n.tagName==='DT').map(font),
                values:entries.filter(n=>n.tagName==='DD').map(font),
                clipped:entries.filter(n=>{
                  const box=n.getBoundingClientRect();
                  return n.scrollWidth>n.clientWidth+1 || box.left<panel.left
                    || box.right>panel.right || box.top<panel.top || box.bottom>panel.bottom;
                }).map(n=>n.id||n.textContent)};
            }""")
            assert not details["overflow"], (width, height, plan, view, details)
            assert details["clipped"] == [], (width, height, plan, view, details)
            assert all(style == details["labels"][0] for style in details["labels"])
            assert all(style == details["values"][0] for style in details["values"])
            styles[view] = {"label": details["labels"][0], "value": details["values"][0]}
            assert styles[view]["label"]["size"] == "11px"
            assert styles[view]["label"]["weight"] == "400"
            assert styles[view]["value"]["size"] == "12px"
            assert styles[view]["value"]["weight"] == "500"
            assert "tabular-nums" in styles[view]["value"]["numbers"]
            assert styles[view]["label"]["height"] == styles[view]["value"]["height"] == "17px"
            assert "Inter" in styles[view]["value"]["family"]
            assert page.locator(".inspector-card").bounding_box() == card_bounds
        assert styles["selection"] == styles["evaluation"]
    assert page.evaluate("elements.globe.getBoundingClientRect().toJSON()") == map_bounds
    assert page.evaluate("JSON.stringify(state.referenceData)") == source
    assert_single_screen(page)


def test_missing_font_uses_system_fallback_without_blocking_the_archive(
    page: Any, lab_url: str
) -> None:
    page.route("**/fonts/InterVariable.woff2", lambda route: route.abort())
    reference_ready(page, lab_url)
    assert not page.evaluate(
        "[...document.fonts].some(f => f.family === 'Inter' && f.status === 'loaded')"
    )
    assert page.locator(".map-marker").count() == 500
    assert page.locator("#solver-select").is_enabled()
    assert_single_screen(page)


@pytest.mark.parametrize(("width", "height"), [(1920, 1080), (1440, 900), (375, 667)])
def test_command_panels_fit_and_decorative_frames_do_not_block_controls(
    page: Any, lab_url: str, width: int, height: int
) -> None:
    page.set_viewport_size({"width": width, "height": height})
    reference_ready(page, lab_url)
    source = page.evaluate("JSON.stringify(state.currentPayload)")
    assert page.locator(".command-card").count() == 6
    assert page.locator(".header-rule").get_attribute("aria-hidden") == "true"
    for view in ["map", "tasks", "summary"]:
        if width <= 1000:
            page.locator(f"#workspace-{view}").click()
        cards = page.locator(".command-card:visible").evaluate_all("""nodes => nodes.map(n => {
          const box = n.getBoundingClientRect();
          return {name:n.className, x:box.x, y:box.y, right:box.right, bottom:box.bottom,
            scroll:n.scrollHeight, height:n.clientHeight,
            pointer:getComputedStyle(n,'::after').pointerEvents};
        })""")
        for card in cards:
            assert 0 <= card["x"] < card["right"] <= width, card
            assert 0 <= card["y"] < card["bottom"] <= height, card
            assert card["scroll"] <= card["height"] + 1, card
            assert card["pointer"] == "none", card
        assert_single_screen(page)
    if width <= 1000:
        page.locator("#workspace-summary").click()
    plans = set(page.locator("#comparison-legend button").all_text_contents())
    assert len(plans) == 7
    assert page.evaluate("JSON.stringify(state.currentPayload)") == source
    assert_single_screen(page)


@pytest.mark.parametrize(("width", "height"), [(1440, 900), (800, 600), (375, 667)])
def test_fov_footprints_and_all_layer_controls_remain_reachable_on_small_screens(
    page: Any, lab_url: str, width: int, height: int
) -> None:
    page.set_viewport_size({"width": width, "height": height})
    reference_ready(page, lab_url)
    assert page.evaluate("SensorFov.ANGLE_DEG") == 45
    assert page.evaluate("SensorFov.HALF_ANGLE") == pytest.approx(22.5 * math.pi / 180)
    assert page.locator("#toggle-fov").text_content() == "Sensor FOV · 45°"
    assert "full cone angle 45°, half-angle 22.5°" in page.locator("#toggle-fov").get_attribute(
        "title"
    )
    assert page.locator(".map-fov").count() == 20
    grounded = page.evaluate("""() => state.currentPayload.replay.orbits.filter(o => {
      const attitude = satelliteFrame(o.satellite_id);
      return SensorFov.frame(state.orbitModels.get(o.satellite_id).cartesian(state.replay.time),
        attitude.direction, attitude.x).footprint.length;
    }).length""")
    assert page.locator(".map-fov polyline").count() >= grounded
    page.locator("#toggle-layers").click()
    assert page.locator("#toggle-illumination").is_disabled()
    assert page.locator("#sun-direction").count() == 0
    page.locator("#toggle-fov").click()
    assert page.locator("#toggle-fov").get_attribute("aria-pressed") == "false"
    assert page.locator(".map-fov:visible").count() == 0
    page.locator("#toggle-fov").click()
    assert page.locator(".map-fov:visible").count() == grounded
    page.locator("#toggle-sat-labels").click()
    assert page.locator("#toggle-sat-labels").get_attribute("aria-pressed") == "false"
    page.keyboard.press("Escape")
    page.evaluate("setReplayTime(-3*86400, true)")
    assert page.locator(".map-fov polyline").count() >= 20
    assert page.locator(".map-ray").count() == 0
    assert_single_screen(page)


def test_gradient_selection_surfaces_keep_small_text_readable(page: Any, lab_url: str) -> None:
    reference_ready(page, lab_url)
    contrast = page.evaluate("""() => {
      const rgb = value => value.match(/[\\d.]+/g).map(Number);
      const hex = value => [1,3,5].map(index => parseInt(value.slice(index,index+2),16));
      const luminance = color => color.slice(0,3).map(c => c/255)
        .map(c => c <= .04045 ? c/12.92 : ((c+.055)/1.055)**2.4)
        .reduce((sum,c,i) => sum+c*[.2126,.7152,.0722][i],0);
      const ratio = (a,b) => (Math.max(luminance(a),luminance(b))+.05)
        / (Math.min(luminance(a),luminance(b))+.05);
      const text = rgb(getComputedStyle(document.querySelector('.task-sublabel')).fill);
      const results = [...document.querySelectorAll('#timeline-lane-active stop')]
        .map(stop => ratio(text,hex(stop.getAttribute('stop-color'))));
      const selected = document.querySelector('.target-row.is-selected');
      const foreground = rgb(getComputedStyle(selected.querySelector('small')).color);
      const gradient = getComputedStyle(selected).backgroundImage;
      for (const match of gradient.matchAll(/rgba?\\([^)]*\\)/g)) {
        results.push(ratio(foreground,rgb(match[0])));
      }
      return Math.min(...results);
    }""")
    assert contrast >= 4.5


def test_premium_status_chips_follow_task_state_and_respect_reduced_motion(
    page: Any, lab_url: str
) -> None:
    page.emulate_media(reduced_motion="reduce")
    reference_ready(page, lab_url)
    source = page.evaluate("JSON.stringify(state.referenceData)")
    assert (
        page.locator("#comparison-chart svg").evaluate(
            "node => getComputedStyle(node).animationName"
        )
        == "none"
    )
    chip = page.locator("#selected-state")
    for time, label, colour in [
        (0, "Observing", [237, 199, 138]),
        (9, "Completed", [117, 217, 182]),
        (-1, "Planned", [115, 195, 219]),
    ]:
        page.evaluate("time => setReplayTime(time, true)", time)
        assert chip.text_content() == label
        assert chip.get_attribute("data-state") == label
        components = chip.evaluate(
            r"node => getComputedStyle(node).backgroundColor.match(/[\d.]+/g).map(Number)"
        )
        assert components[:3] == colour
        assert 0 < components[3] < 0.06
    page.locator('.target-row[data-state="Unassigned"]').first.click()
    assert chip.text_content() == "Unassigned"
    assert chip.evaluate(
        r"node => getComputedStyle(node).backgroundColor.match(/[\d.]+/g).map(Number).slice(0,3)"
    ) == [243, 156, 168]
    assert page.locator(".workload-value").evaluate_all("""nodes => nodes.every(node => {
      const row = node.closest('.workload-row');
      const load = state.currentPayload.reference_plan.workloads[row.dataset.satelliteId];
      return node.textContent === `${load} s`
        && node.querySelector('.workload-unit').textContent === ' s';
    })""")
    assert page.evaluate("JSON.stringify(state.referenceData)") == source
    assert_single_screen(page)


@pytest.mark.parametrize("time", [0, 11])
def test_small_text_has_readable_contrast_in_default_and_selected_states(
    page: Any, lab_url: str, time: int
) -> None:
    reference_ready(page, lab_url)
    page.evaluate("time=>setReplayTime(time,true)", time)
    samples = page.evaluate("""() => {
      const rgb = value => value.match(/[\\d.]+/g).map(Number);
      const luminance = color => color.slice(0, 3).map(c => c / 255)
        .map(c => c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4)
        .reduce((sum, c, i) => sum + c * [.2126, .7152, .0722][i], 0);
      return [...document.querySelectorAll(
        '.target-row-name small, .target-state, .selection-details dt, '
        + '.selection-details dd, .radar-legend button, .radar-values dt, .radar-values dd, '
        + '.pager > span, .status')].map(node => {
          const foreground = rgb(getComputedStyle(node).color);
          let current = node, background;
          while (current) {
            const color = rgb(getComputedStyle(current).backgroundColor);
            if (color.length === 3 || color[3] === 1) { background = color; break; }
            current = current.parentElement;
          }
          const a = luminance(foreground), b = luminance(background);
          return {label:node.textContent, contrast:(Math.max(a,b)+.05)/(Math.min(a,b)+.05)};
        });
    }""")
    for sample in samples:
        assert sample["contrast"] >= 4.5, sample


def test_paused_replay_reuses_fallback_geometry_and_does_not_rewrite_task_dom(
    page: Any, lab_url: str
) -> None:
    reference_ready(page, lab_url)
    page.evaluate("setReplayTime(1200,true)")
    page.wait_for_function("state.ephemeris.pendingCount === 0")
    result = page.evaluate("""() => {
      updateReplayVisuals();
      const source=JSON.stringify(state.referenceData), original=window.SensorFov;
      let frames=0;
      window.SensorFov={...original,frame(...args){frames++;return original.frame(...args);}};
      const records=new MutationObserver(()=>{});
      for(const id of ['target-list','mission-globe']) records.observe(document.getElementById(id),
        {attributes:true,childList:true,subtree:true,characterData:true});
      try {
        for(let i=0;i<50;i++) updateReplayVisuals();
        return {frames,mutations:records.takeRecords().length,
          unchanged:source===JSON.stringify(state.referenceData)};
      } finally {records.disconnect();window.SensorFov=original;}
    }""")
    assert result == {"frames": 0, "mutations": 0, "unchanged": True}


def test_task_state_index_remains_linked_after_filters_plan_changes_and_reverse_seeks(
    page: Any, lab_url: str
) -> None:
    reference_ready(page, lab_url)
    for plan in ["eos-sa-profit", "eos-greedy-profit", "eos-sa-balanced"]:
        page.select_option("#solver-select", plan)
        page.wait_for_function(
            "id => !state.busy && state.currentPayload.reference_plan.plan_id === id", arg=plan
        )
        for time in [0, 1200.25, 43199, 43200, -1, 3600, 1]:
            result = page.evaluate(
                """time => {
                  setReplayTime(time,true);
                  const scenario=state.currentPayload.scenario;
                  const errors=[];
                  for(const node of document.querySelectorAll(
                    '.target-row,.map-marker,.task-bar[data-task-id]')) {
                    const id=node.dataset.taskId, assignment=state.assignments.get(id);
                    const outside=time<scenario.horizon_start_s||time>=scenario.horizon_end_s;
                    const planned=time<scenario.horizon_start_s?'Planned':'Completed';
                    const windows=state.taskById.get(id).visibility_windows;
                    const expected=outside
                      ? (assignment ? planned:'Unassigned')
                      : OrbitReplay.taskState(time,assignment,windows);
                    if(node.dataset.state!==expected) errors.push(id);
                  }
                  return errors;
                }""",
                time,
            )
            assert result == []
        page.select_option("#target-filter", "active")
        page.evaluate(
            "setReplayTime(state.currentPayload.reference_plan.assignments[0].start_s,true)"
        )
        assert page.locator(".target-row").count() > 0
        page.select_option("#target-filter", "all")


@pytest.mark.parametrize(
    ("width", "height"),
    [(1920, 1080), (1440, 900), (1280, 720), (1024, 768), (800, 600), (390, 844), (375, 667)],
)
def test_playback_and_plan_changes_keep_the_two_inspector_views_without_broadcasts(
    page: Any, lab_url: str, width: int, height: int
) -> None:
    page.set_viewport_size({"width": width, "height": height})
    reference_ready(page, lab_url)
    if width <= 1000:
        page.locator("#workspace-summary").click()
    tabs = page.get_by_role("tablist", name="Inspector views")
    assert tabs.get_by_role("tab").all_text_contents() == ["Selection", "Metrics"]
    assert page.locator("#tab-live, #inspector-live, #live-announcement, .live-task").count() == 0
    assert page.locator("#tab-selection").get_attribute("aria-selected") == "true"
    map_bounds = page.evaluate("elements.globe.getBoundingClientRect().toJSON()")
    card_bounds = page.locator(".inspector-card").bounding_box()
    selected = page.evaluate("[state.selectedTaskId,state.selectedSatelliteId,state.cameraMode]")
    source = page.evaluate("JSON.stringify(state.currentPayload)")
    for view in ["selection", "evaluation"]:
        page.locator(f"#tab-{view}").click()
        # Playback controls remain mounted while Results is visible on small screens.
        page.locator("#replay-play").dispatch_event("click")
        page.wait_for_function("state.replay.playing && state.replay.time > 0")
        page.locator("#replay-play").dispatch_event("click")
        assert not page.evaluate("state.replay.playing")
        for time in [0, 7.5, 8, 11, 25253, 43200, -1, 86400, 0]:
            page.evaluate("time=>setReplayTime(time,true)", time)
            assert page.locator(f"#inspector-{view}").is_visible()
            assert page.locator(f"#tab-{view}").get_attribute("aria-selected") == "true"
            assert (
                page.evaluate("[state.selectedTaskId,state.selectedSatelliteId,state.cameraMode]")
                == selected
            )
        assert page.locator(".inspector-card").bounding_box() == card_bounds
        assert page.evaluate("elements.globe.getBoundingClientRect().toJSON()") == map_bounds
    assert page.evaluate("JSON.stringify(state.currentPayload)") == source
    page.select_option("#solver-select", "eos-greedy-profit")
    page.wait_for_function(
        "!state.busy && state.currentPayload.reference_plan.plan_id==='eos-greedy-profit'"
    )
    assert page.locator("#inspector-evaluation").is_visible()
    assert tabs.get_by_role("tab").all_text_contents() == ["Selection", "Metrics"]
    page.locator("#tab-selection").click()
    assert page.locator("#selected-id").text_content() == page.evaluate("state.selectedTaskId")
    assert_single_screen(page)
