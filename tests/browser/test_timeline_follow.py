"""Opt-in native Cesium tests for satellite selection from Timeline."""

from __future__ import annotations

import os
from typing import Any

import pytest

from tests.browser.test_globe import cesium_assets as cesium_assets
from tests.browser.test_globe import globe_page as globe_page
from tests.browser.test_globe import native_camera_snapshot
from tests.browser.test_workbench import browser as browser
from tests.browser.test_workbench import lab_url as lab_url

pytestmark = pytest.mark.skipif(
    os.environ.get("ORBITOPS_GLOBE_TESTS") != "1", reason="real WebGL verification is opt-in"
)


@pytest.mark.parametrize("interaction", ["label", "lane", "Enter", "Space"])
@pytest.mark.parametrize("playing", [False, True])
def test_timeline_rows_switch_3d_follow_without_seeking_or_stopping_playback(
    globe_page: Any, interaction: str, playing: bool
) -> None:
    page = globe_page
    source = page.evaluate("JSON.stringify(state.currentPayload)")
    page.evaluate("setReplayTime(100,true);selectSatellite('KENT_RIDGE_1_41167')")
    page.locator("#camera-follow").click()
    page.wait_for_function("state.globe.trackedEntity?.id==='satellite-KENT_RIDGE_1_41167'")
    task = page.evaluate("state.selectedTaskId")
    page.locator("#replay-speed").select_option("1")
    if playing:
        page.locator("#replay-play").click()
    # Include a zero-workload satellite and a second switch in the same session.
    for satellite in ["SCD_2_25504", "ALOS-2_39766"]:
        row = page.locator(f'.satellite-lane[data-satellite-id="{satellite}"]')
        label = row.locator(".satellite-lane-label")
        if interaction in {"Enter", "Space"}:
            label.focus()
            label.press(interaction)
        elif interaction == "label":
            label.click()
        else:
            band = row.locator(".row-band")
            band.scroll_into_view_if_needed()
            bounds = band.bounding_box()
            assert bounds is not None
            band.click(position={"x": bounds["width"] - 4, "y": bounds["height"] / 2})
        page.wait_for_function(
            "id=>state.selectedSatelliteId===id && state.cameraMode==='follow' "
            "&& state.globe.trackedEntity?.id==='satellite-'+id",
            arg=satellite,
        )
        assert page.evaluate("state.selectedTaskId") == task
        assert page.evaluate("state.replay.playing") is playing
        time = page.evaluate("state.replay.time")
        assert (100 <= time < 130) if playing else time == 100
        assert page.locator("#camera-follow").get_attribute("aria-pressed") == "true"
        assert (
            page.locator(".satellite-lane.is-selected").get_attribute("data-satellite-id")
            == satellite
        )
        assert (
            page.locator('.workload-row[aria-pressed="true"]').get_attribute("data-satellite-id")
            == satellite
        )
        assert label.get_attribute("aria-pressed") == "true"
        if interaction in {"Enter", "Space"}:
            assert label.evaluate("node=>node===document.activeElement")
    # Re-selecting the tracked row must not recreate EntityView or reset zoom.
    if playing:
        page.locator("#replay-play").click()
    page.wait_for_timeout(100)
    camera = native_camera_snapshot(page)
    page.evaluate("() => { window.originalTrackedSatellite=state.globe.trackedEntity; }")
    page.locator(".satellite-lane.is-selected .satellite-lane-label").click()
    page.wait_for_timeout(100)
    assert page.evaluate("state.globe.trackedEntity===originalTrackedSatellite")
    assert native_camera_snapshot(page) == pytest.approx(camera, abs=1e-6, rel=0)
    assert page.evaluate("JSON.stringify(state.currentPayload)") == source


@pytest.mark.parametrize(
    ("projection", "camera_mode", "interaction"),
    [
        ("3d", "follow", "click"),
        ("3d", "follow", "Enter"),
        ("3d", "follow", "Space"),
        ("3d", "overview", "click"),
        ("2d", "follow", "click"),
        ("2.5d", "follow", "click"),
    ],
)
def test_timeline_task_bars_keep_follow_only_in_3d_and_preserve_task_seeks(
    globe_page: Any, projection: str, camera_mode: str, interaction: str
) -> None:
    page = globe_page
    if projection != "3d":
        page.evaluate("mode=>setMapViewMode(mode)", projection)
        page.wait_for_function("!state.viewTransition")
    page.evaluate("setReplayTime(100,true);selectSatellite('KENT_RIDGE_1_41167')")
    page.locator(f"#camera-{camera_mode}").click()
    source = page.evaluate("JSON.stringify(state.currentPayload)")
    candidate = page.evaluate("""() => {
      const row=[...document.querySelectorAll('.satellite-lane')].find(
        row=>row.dataset.satelliteId!==state.selectedSatelliteId && row.querySelector('.task-bar'));
      const id=[...row.querySelectorAll('.task-bar:not([hidden])')].at(-1).dataset.taskId;
      const assignment=state.assignments.get(id);
      return {task:id,satellite:assignment.satellite_id,time:assignment.start_s};
    }""")
    bar = page.locator(f'.task-bar[data-task-id="{candidate["task"]}"]')
    bar.scroll_into_view_if_needed()
    before = native_camera_snapshot(page)
    if interaction == "click":
        bar.click()
    else:
        bar.focus()
        bar.press(interaction)
    assert page.evaluate("state.selectedTaskId") == candidate["task"]
    assert page.evaluate("state.replay.time") == candidate["time"]
    assert not page.evaluate("state.replay.playing")
    assert page.locator("#selected-id").text_content() == candidate["task"]
    assert page.locator("#tab-selection").get_attribute("aria-selected") == "true"
    if projection == "3d" and camera_mode == "follow":
        page.wait_for_function(
            "id=>state.globe.trackedEntity?.id==='satellite-'+id", arg=candidate["satellite"]
        )
        assert page.evaluate("state.cameraMode") == "follow"
        assert page.evaluate("state.selectedSatelliteId") == candidate["satellite"]
        assert page.locator("#camera-follow").get_attribute("aria-pressed") == "true"
    else:
        assert page.evaluate("state.selectedSatelliteId") is None
        assert page.evaluate("!state.globe.trackedEntity")
        assert page.evaluate("state.cameraMode") == (
            "manual" if camera_mode == "follow" else camera_mode
        )
        assert native_camera_snapshot(page) == pytest.approx(before, abs=1e-6, rel=0)
    assert page.evaluate("JSON.stringify(state.currentPayload)") == source
