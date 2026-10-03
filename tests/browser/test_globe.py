"""Opt-in tests against the real Cesium/WebGL runtime, not a renderer mock.

Run ORBITOPS_GLOBE_TESTS=1 pytest tests/browser/test_globe.py with Chrome installed.
The official Cesium CDN must be reachable on each asset's first request. Exact
response bytes are cached across tests, not replaced with a renderer mock. NASA
requests are deliberately blocked to exercise the Natural Earth imagery fallback.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.browser.test_workbench import assert_single_screen
from tests.browser.test_workbench import browser as browser
from tests.browser.test_workbench import lab_url as lab_url

pytestmark = pytest.mark.skipif(
    os.environ.get("ORBITOPS_GLOBE_TESTS") != "1", reason="real WebGL verification is opt-in"
)
SCREENSHOTS = Path(__file__).parents[2] / "runs" / "ui-review"


@pytest.fixture(scope="module")
def cesium_assets() -> dict[str, tuple[int, dict[str, str], bytes]]:
    return {}


@pytest.fixture
def globe_page(
    browser: Any, lab_url: str, cesium_assets: dict[str, tuple[int, dict[str, str], bytes]]
) -> Iterator[Any]:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    context.route("https://gibs.earthdata.nasa.gov/**", lambda route: route.abort())

    def official_asset(route: Any) -> None:
        url = route.request.url
        if url not in cesium_assets:
            response = route.fetch(timeout=30000, max_retries=2)
            headers = {
                key: value
                for key, value in response.headers.items()
                if key.lower() not in {"content-encoding", "content-length"}
            }
            asset = (response.status, headers, response.body())
            if response.ok:
                cesium_assets[url] = asset
        else:
            asset = cesium_assets[url]
        status, headers, body = asset
        route.fulfill(status=status, headers=headers, body=body)

    context.route("https://cesium.com/**", official_asset)
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(lab_url, wait_until="domcontentloaded")
    page.wait_for_function(
        "state.globe && state.orbitPositions.size === 20 && !state.busy", timeout=45000
    )
    page.evaluate("""() => {
      window.renderErrors = [];
      state.globe.scene.renderError.addEventListener((scene, error) => {
        renderErrors.push(String(error));
      });
    }""")
    page.wait_for_function("state.globe.dataSourceDisplay.ready", timeout=15000)
    page.wait_for_timeout(300)
    try:
        yield page
        assert not errors, errors
        assert page.evaluate("renderErrors") == []
        assert page.evaluate("state.globe.useDefaultRenderLoop")
    finally:
        context.unroute_all(behavior="ignoreErrors")
        context.close()


def test_real_globe_has_startup_tracks_symbols_and_unmodified_source_positions(
    globe_page: Any,
) -> None:
    scene = globe_page.evaluate("""() => {
      const viewer = state.globe;
      return {
        satellites: viewer.entities.values.filter(e => e.id.startsWith('satellite-')).length,
        targets: viewer.entities.values.filter(e => e.id.startsWith('target-')).length,
        paths: state.currentPayload.replay.orbits.map(orbit => {
          const future = viewer.entities.getById('orbit-preview-' + orbit.satellite_id).path;
          const past = viewer.entities.getById('orbit-' + orbit.satellite_id).path;
          const satellite = viewer.entities.getById('satellite-' + orbit.satellite_id);
          const sample = orbit.samples[0];
          return {future:future.leadTime.getValue(), period:orbit.period_s,
            pastShown:past.show.getValue(), futureShown:future.show.getValue(),
            sourceError:Cesium.Cartesian3.distance(satellite.position.getValue(viewer.clock.currentTime),
              Cesium.Cartesian3.fromDegrees(sample[1],sample[2],sample[3])),
            symbol:Boolean(satellite.billboard.image.getValue()),
            depth:satellite.billboard.disableDepthTestDistance.getValue()};
        })
      };
    }""")
    assert scene["satellites"] == 20
    assert scene["targets"] == 500
    for orbit in scene["paths"]:
        assert orbit["future"] == pytest.approx(orbit["period"])
        assert orbit["futureShown"] and not orbit["pastShown"]
        assert orbit["symbol"] and orbit["depth"] == 0
        assert orbit["sourceError"] < 0.001
    globe_page.wait_for_function(
        "elements.globe.dataset.imagerySource === 'natural-earth-fallback'"
    )
    globe_page.evaluate("setReplayTime(15, true)")
    displayed_altitude = globe_page.evaluate("""() => {
      const point = state.orbitPositions.get(state.selectedSatelliteId)
        .getValue(state.globe.clock.currentTime);
      return (Cesium.Cartographic.fromCartesian(point).height / 1000).toFixed(1) + ' km';
    }""")
    assert globe_page.locator("#satellite-altitude").inner_text() == displayed_altitude
    assert_single_screen(globe_page)


def test_satellite_canvas_picking_focus_follow_and_source_horizon(globe_page: Any) -> None:
    candidate = globe_page.wait_for_function(
        """() => {
      const viewer = state.globe;
      const box = elements.globe.getBoundingClientRect();
      const hud = document.getElementById('orbit-hud').getBoundingClientRect();
      const occluder = new Cesium.EllipsoidalOccluder(
        Cesium.Ellipsoid.WGS84, viewer.camera.positionWC);
      for (const entity of viewer.entities.values.filter(e => e.id.startsWith('satellite-'))) {
        const position = entity.position.getValue(viewer.clock.currentTime);
        if (!occluder.isPointVisible(position)) continue;
        const point = Cesium.SceneTransforms.worldToWindowCoordinates(viewer.scene, position);
        if (!point || point.x < 30 || point.x > box.width - 30
            || point.y < 30 || point.y > box.height - 30) continue;
        const x = box.left + point.x, y = box.top + point.y;
        if (x >= hud.left && x <= hud.right && y >= hud.top && y <= hud.bottom) continue;
        if (document.elementFromPoint(x, y) !== viewer.canvas) continue;
        if (pickedMissionObject(viewer, point)?.id !== entity.id.slice(10)) continue;
        return {id:entity.id.slice(10), x, y};
      }
      return null; // Billboard textures become pickable after their first rendered frame.
    }""",
        timeout=10000,
    ).json_value()
    globe_page.mouse.move(candidate["x"], candidate["y"])
    globe_page.wait_for_function("!document.getElementById('globe-hover').hidden")
    globe_page.mouse.click(candidate["x"], candidate["y"])
    assert globe_page.locator("#satellite-name").get_attribute("title") == candidate["id"]
    globe_page.locator("#camera-focus").click()
    globe_page.wait_for_function("state.cameraMode === 'focus'")
    globe_page.wait_for_timeout(750)
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    globe_page.screenshot(path=str(SCREENSHOTS / "geometry-focus.png"))
    globe_page.locator("#camera-follow").click()
    globe_page.wait_for_function(
        "state.globe.trackedEntity?.id === 'satellite-' + state.selectedSatelliteId"
    )
    before = globe_page.evaluate("Cesium.Cartesian3.clone(state.globe.camera.positionWC)")
    globe_page.evaluate("setReplayTime(1800, true)")
    globe_page.wait_for_timeout(300)
    after = globe_page.evaluate("Cesium.Cartesian3.clone(state.globe.camera.positionWC)")
    assert before != after
    assert (
        globe_page.evaluate("""() => Cesium.Cartesian3.distance(
      state.globe.camera.positionWC,
      state.globe.trackedEntity.position.getValue(state.globe.clock.currentTime))
    """)
        < 6000000
    )
    globe_page.screenshot(path=str(SCREENSHOTS / "geometry-follow.png"))
    globe_page.evaluate("setReplayTime(43200, true)")
    assert globe_page.evaluate("""() => state.currentPayload.replay.orbits.every(orbit => {
      const past = state.globe.entities.getById('orbit-' + orbit.satellite_id).path;
      const future = state.globe.entities.getById('orbit-preview-' + orbit.satellite_id).path;
      return past.show.getValue() && !future.show.getValue() && future.leadTime.getValue() === 0;
    })""")
    globe_page.locator("#camera-overview").click()
    assert globe_page.evaluate("!state.globe.trackedEntity")
    assert globe_page.locator("#camera-overview").get_attribute("aria-pressed") == "true"
    globe_page.locator("#toggle-track").click()
    assert globe_page.evaluate(
        "state.globe.entities.values.filter(e=>e.path).every(e=>!e.path.show.getValue())"
    )


@pytest.mark.parametrize(("width", "height"), [(1800, 1000), (1366, 768), (390, 844)])
def test_globe_camera_refits_after_resize_and_map_expansion(
    globe_page: Any, width: int, height: int
) -> None:
    globe_page.set_viewport_size({"width": width, "height": height})
    globe_page.wait_for_timeout(250)
    globe_page.locator("#expand-map").click()
    globe_page.wait_for_timeout(300)
    framing = globe_page.evaluate("""() => {
      const camera = state.globe.camera;
      const halfVertical = camera.frustum.fovy / 2;
      const halfHorizontal = Math.atan(Math.tan(halfVertical) * camera.frustum.aspectRatio);
      const distance = Cesium.Cartesian3.magnitude(camera.positionWC);
      return {angularRadius:Math.asin(state.cameraHome.missionCenter.radius / distance),
        limit:Math.min(halfVertical,halfHorizontal)};
    }""")
    assert framing["angularRadius"] < framing["limit"]
    assert_single_screen(globe_page)
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    globe_page.screenshot(path=str(SCREENSHOTS / f"geometry-expanded-{width}.png"))
    globe_page.locator("#expand-map").click()
    assert globe_page.locator(".analysis-dock").is_visible()
    assert_single_screen(globe_page)


def test_local_mode_clears_satellite_tracking_and_reference_geometry(globe_page: Any) -> None:
    globe_page.locator("#camera-follow").click()
    assert globe_page.evaluate("Boolean(state.globe.trackedEntity)")
    assert globe_page.evaluate("""() => state.currentPayload.replay.orbits
      .filter(orbit => orbit.satellite_id !== state.selectedSatelliteId)
      .every(orbit => state.globe.entities.getById('orbit-preview-' + orbit.satellite_id)
        .path.material === state.orbitStyles.get(orbit.satellite_id).dimmed.future)
    """)
    globe_page.locator("#scenario-select").select_option("showcase-resources-10")
    globe_page.locator("#solver-select").select_option("greedy-insertion")
    globe_page.locator("#run-button").click()
    globe_page.wait_for_function("state.currentPayload.mode !== 'reference' && !state.busy")
    assert globe_page.locator("#orbit-hud").is_hidden()
    assert globe_page.evaluate("!state.globe.trackedEntity && state.orbitPositions.size === 0")
    assert globe_page.evaluate(
        "!state.globe.entities.values.some(e=>e.id.startsWith('satellite-') || e.path)"
    )
    assert_single_screen(globe_page)


@pytest.mark.parametrize(("selector", "mode"), [("#view-2d", "2d"), ("#view-2_5d", "2.5d")])
@pytest.mark.parametrize(("width", "height"), [(1800, 1000), (390, 844)])
def test_unfolded_scene_preserves_source_replay_and_fits_after_expansion(
    globe_page: Any, selector: str, mode: str, width: int, height: int
) -> None:
    globe_page.set_viewport_size({"width": width, "height": height})
    globe_page.evaluate("setReplayTime(12345, true)")
    selection = globe_page.evaluate("[state.selectedTaskId, state.selectedSatelliteId]")
    globe_page.locator(selector).click()
    globe_page.wait_for_function(
        "mode => state.viewMode === mode && !state.viewTransition", arg=mode
    )
    assert globe_page.locator(selector).get_attribute("aria-pressed") == "true"
    assert globe_page.evaluate("[state.selectedTaskId, state.selectedSatelliteId]") == selection
    assert globe_page.evaluate("state.replay.time") == 12345
    assert globe_page.evaluate("""() => state.currentPayload.replay.orbits.every(orbit => {
      const entity = state.globe.entities.getById('satellite-' + orbit.satellite_id);
      const original = orbit.samples.find(sample => sample[0] === 12330);
      return Cesium.Cartesian3.distance(
        entity.position.getValue(Cesium.JulianDate.addSeconds(state.globe.clock.startTime,
          original[0],new Cesium.JulianDate())),
        Cesium.Cartesian3.fromDegrees(original[1],original[2],original[3])) < .001;
    })""")
    for expanded in [True, False]:
        globe_page.locator("#expand-map").click()
        globe_page.wait_for_timeout(300)
        corners = globe_page.evaluate("""() => {
          const viewer = state.globe;
          return [-179.9,179.9].flatMap(lon => [-89.9,89.9].flatMap(lat =>
            [0,876536].map(alt => {
              const point = Cesium.SceneTransforms.worldToWindowCoordinates(viewer.scene,
                Cesium.Cartesian3.fromDegrees(lon,lat,alt));
              return point && point.x >= -1 && point.x <= elements.globe.clientWidth + 1
                && point.y >= -1 && point.y <= elements.globe.clientHeight + 1;
            })));
        }""")
        assert all(corners)
        assert_single_screen(globe_page)
        if expanded:
            SCREENSHOTS.mkdir(parents=True, exist_ok=True)
            globe_page.screenshot(path=str(SCREENSHOTS / f"map-{mode}-expanded-{width}.png"))
    globe_page.locator("#view-3d").click()
    globe_page.wait_for_function("state.viewMode === '3d' && !state.viewTransition")
    assert globe_page.evaluate("state.replay.time") == 12345
    assert_single_screen(globe_page)


@pytest.mark.parametrize(("selector", "mode"), [("#view-2d", "2d"), ("#view-2_5d", "2.5d")])
def test_planar_focus_and_follow_keep_the_selected_satellite_in_view(
    globe_page: Any, selector: str, mode: str
) -> None:
    globe_page.locator(selector).click()
    globe_page.wait_for_function(
        "mode => state.viewMode === mode && !state.viewTransition", arg=mode
    )
    globe_page.locator("#camera-focus").click()
    globe_page.wait_for_timeout(800)
    globe_page.locator("#camera-follow").click()
    for time in [1800, 2730, 43199]:
        globe_page.evaluate("time => setReplayTime(time,true)", time)
        globe_page.wait_for_function("""() => {
          const viewer = state.globe;
          const point = Cesium.SceneTransforms.worldToWindowCoordinates(viewer.scene,
            state.orbitPositions.get(state.selectedSatelliteId).getValue(viewer.clock.currentTime));
          return point && Math.abs(point.x - elements.globe.clientWidth / 2) < 5
            && Math.abs(point.y - elements.globe.clientHeight / 2) < 5;
        }""")
        assert globe_page.locator("#camera-follow").get_attribute("aria-pressed") == "true"
    globe_page.locator("#view-3d").click()
    globe_page.wait_for_function("state.viewMode === '3d' && !state.viewTransition")
    assert globe_page.evaluate("!state.globe.trackedEntity && state.cameraMode === 'overview'")
    assert globe_page.evaluate("state.replay.time") == 43199
    assert_single_screen(globe_page)


def test_reduced_motion_and_switching_during_replay_preserve_the_clock(globe_page: Any) -> None:
    globe_page.emulate_media(reduced_motion="reduce")
    for selector, mode in [("#view-2d", "2d"), ("#view-2_5d", "2.5d"), ("#view-3d", "3d")]:
        globe_page.locator(selector).click()
        assert globe_page.evaluate("state.viewMode") == mode
        assert not globe_page.evaluate("state.viewTransition")
    globe_page.locator("#replay-play").click()
    globe_page.locator("#view-2d").click()
    globe_page.wait_for_function("state.replay.time > 30")
    assert globe_page.evaluate("state.replay.playing && state.viewMode === '2d'")
    assert_single_screen(globe_page)


@pytest.mark.parametrize(("selector", "mode"), [("#view-2d", "2d"), ("#view-2_5d", "2.5d")])
def test_local_scenario_retains_planar_view_and_has_no_invented_orbits(
    globe_page: Any, selector: str, mode: str
) -> None:
    globe_page.locator(selector).click()
    globe_page.wait_for_function(
        "mode => state.viewMode === mode && !state.viewTransition", arg=mode
    )
    globe_page.locator("#scenario-select").select_option("showcase-resources-10")
    globe_page.locator("#solver-select").select_option("greedy-insertion")
    globe_page.locator("#run-button").click()
    globe_page.wait_for_function("state.currentPayload.mode !== 'reference' && !state.busy")
    assert globe_page.evaluate("state.viewMode") == mode
    assert globe_page.locator(selector).get_attribute("aria-pressed") == "true"
    assert globe_page.evaluate("!state.globe.trackedEntity && state.orbitPositions.size === 0")
    assert globe_page.evaluate(
        "!state.globe.entities.values.some(e=>e.id.startsWith('satellite-') || e.path)"
    )
    assert globe_page.locator("#orbit-hud").is_hidden()
    assert_single_screen(globe_page)


@pytest.mark.parametrize("selector", ["#view-2d", "#view-2_5d"])
def test_satellites_remain_pickable_on_unfolded_maps(globe_page: Any, selector: str) -> None:
    globe_page.locator(selector).click()
    globe_page.wait_for_function("!state.viewTransition")
    candidate = globe_page.wait_for_function(
        """() => {
      const viewer = state.globe, box = elements.globe.getBoundingClientRect();
      for (const orbit of state.currentPayload.replay.orbits) {
        const point = Cesium.SceneTransforms.worldToWindowCoordinates(viewer.scene,
          state.orbitPositions.get(orbit.satellite_id).getValue(viewer.clock.currentTime));
        if (!point || point.x < 30 || point.x > box.width - 30
          || point.y < 30 || point.y > box.height - 30) continue;
        const x = box.left + point.x, y = box.top + point.y;
        if (document.elementFromPoint(x,y) !== viewer.canvas) continue;
        if (pickedMissionObject(viewer,point)?.id !== orbit.satellite_id) continue;
        return {id:orbit.satellite_id,x,y};
      }
      return null;
    }""",
        timeout=10000,
    ).json_value()
    globe_page.mouse.move(candidate["x"], candidate["y"])
    globe_page.wait_for_function("!document.getElementById('globe-hover').hidden")
    globe_page.mouse.click(candidate["x"], candidate["y"])
    assert globe_page.locator("#satellite-name").get_attribute("title") == candidate["id"]
    assert globe_page.evaluate("""() => state.globe.entities.getById(
      'satellite-' + state.selectedSatelliteId).label.distanceDisplayCondition.getValue().far
    """) == float("inf")
    assert_single_screen(globe_page)


def test_loading_another_plan_during_a_view_transition_keeps_the_scene_healthy(
    globe_page: Any,
) -> None:
    globe_page.evaluate("setMapViewMode('2d')")
    globe_page.locator("#solver-select").select_option("eos-ppo-profit")
    globe_page.locator("#run-button").click()
    globe_page.wait_for_function(
        "state.currentPayload.reference_plan.plan_id === 'eos-ppo-profit' && !state.busy "
        "&& !state.viewTransition"
    )
    assert globe_page.evaluate("state.viewMode") == "2d"
    assert globe_page.locator("#metric-tasks").inner_text() == "492/500"
    assert globe_page.evaluate("state.orbitPositions.size") == 20
    assert_single_screen(globe_page)
