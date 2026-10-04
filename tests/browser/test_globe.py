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

from tests.browser.test_workbench import (
    assert_centered_playback_controls,
    assert_single_screen,
    assert_timeline_playback_alignment,
)
from tests.browser.test_workbench import browser as browser
from tests.browser.test_workbench import lab_url as lab_url

pytestmark = pytest.mark.skipif(
    os.environ.get("ORBITOPS_GLOBE_TESTS") != "1", reason="real WebGL verification is opt-in"
)
SCREENSHOTS = Path(__file__).parents[2] / "runs" / "ui-review"
SCREEN_NORTH_BEARING = """() => {
  const viewer = state.globe, camera = viewer.camera;
  const north = viewer.scene.mode === Cesium.SceneMode.SCENE3D
    ? Cesium.Matrix4.multiplyByPointAsVector(
        Cesium.Transforms.eastNorthUpToFixedFrame(
          viewer.scene.globe.ellipsoid.scaleToGeodeticSurface(camera.positionWC)),
        Cesium.Cartesian3.UNIT_Y,new Cesium.Cartesian3())
    : Cesium.Cartesian3.UNIT_Z;
  // Independently project a north-directed segment at the screen centre with
  // native view/projection matrices, not the production bearing formula.
  const centre = Cesium.Cartesian3.add(camera.positionWC,
    Cesium.Cartesian3.multiplyByScalar(camera.directionWC,1000000,new Cesium.Cartesian3()),
    new Cesium.Cartesian3());
  const tip = Cesium.Cartesian3.add(centre,
    Cesium.Cartesian3.multiplyByScalar(north,1000,new Cesium.Cartesian3()),
    new Cesium.Cartesian3());
  // Work in scene coordinates: distant unfolded cameras can be outside valid
  // geographic latitudes, where a WGS84 conversion would wrap the test segment.
  const project = point => {
    const eye = Cesium.Matrix4.multiplyByVector(camera.viewMatrix,
      new Cesium.Cartesian4(point.x,point.y,point.z,1),new Cesium.Cartesian4());
    const clip = Cesium.Matrix4.multiplyByVector(camera.frustum.projectionMatrix,
      eye,new Cesium.Cartesian4());
    return {x:(clip.x/clip.w+1)*viewer.canvas.clientWidth/2,
      y:(1-clip.y/clip.w)*viewer.canvas.clientHeight/2};
  };
  const a = project(centre), b = project(tip);
  return (360 - Cesium.Math.toDegrees(Math.atan2(b.x-a.x,a.y-b.y))) % 360;
}"""


def assert_compass_matches_screen_north(page: Any) -> None:
    snapshot = page.evaluate(f"""() => {{
      const expected = ({SCREEN_NORTH_BEARING})();
      const actual = Number(document.getElementById('north-view').dataset.heading);
      const matrix = document.querySelector('.compass-north-label').getCTM();
      return {{expected,actual,upright:Math.atan2(matrix.b,matrix.a)}};
    }}""")
    expected, actual = snapshot["expected"], snapshot["actual"]
    error = (actual - expected + 180) % 360 - 180
    assert error == pytest.approx(0, abs=0.006), (actual, expected)
    assert snapshot["upright"] == pytest.approx(0, abs=1e-10)


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
            # Use Chrome's network path, including its system proxy, rather than
            # the separate API-request client used by route.fetch().
            route.continue_()
            return
        status, headers, body = cesium_assets[url]
        route.fulfill(status=status, headers=headers, body=body)

    context.route("https://cesium.com/**", official_asset)
    page = context.new_page()

    def cache_official_asset(request: Any) -> None:
        if not request.url.startswith("https://cesium.com/") or request.url in cesium_assets:
            return
        response = request.response()
        if response is None or not response.ok:
            return
        headers = {
            key: value
            for key, value in response.headers.items()
            if key.lower() not in {"content-encoding", "content-length"}
        }
        cesium_assets[request.url] = (response.status, headers, response.body())

    page.on("requestfinished", cache_official_asset)
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


@pytest.mark.parametrize("viewport", [(1440, 900), (800, 600), (375, 667)])
def test_native_timeline_scrubber_and_window_buttons_share_the_globe_clock(
    globe_page: Any, viewport: tuple[int, int]
) -> None:
    globe_page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
    globe_page.wait_for_timeout(150)
    source = globe_page.evaluate("JSON.stringify(state.currentPayload)")
    assert_centered_playback_controls(globe_page)
    assert_timeline_playback_alignment(globe_page)
    globe_page.locator("#replay-scrub").evaluate(
        "node => {node.value = 5; node.dispatchEvent(new Event('input'));}"
    )
    assert globe_page.locator("#selected-state").text_content() == "Observing"
    assert_timeline_playback_alignment(globe_page)
    for button, expected in [
        ("replay-window-prev", -43195),
        ("replay-window-next", 5),
        ("replay-window-next", 43205),
    ]:
        globe_page.locator(f"#{button}").click()
        assert globe_page.evaluate("state.replay.time") == expected
        clock = globe_page.evaluate("""() => Cesium.JulianDate.secondsDifference(
          state.globe.clock.currentTime,
          Cesium.JulianDate.fromIso8601(state.currentPayload.scenario.epoch_utc))""")
        assert clock == pytest.approx(expected)
        assert_timeline_playback_alignment(globe_page)
        if expected != 5:
            assert globe_page.locator(".task-bar:not([hidden]), .window-bar").count() == 0
            assert (
                globe_page.evaluate(
                    "state.globe.entities.values.filter(e=>e.id.startsWith('ray-')).length"
                )
                == 0
            )
    globe_page.locator("#replay-reset").click()
    assert globe_page.locator(".task-bar:not([hidden])").count() == 488
    assert globe_page.evaluate("JSON.stringify(state.currentPayload)") == source
    assert_single_screen(globe_page)


def test_native_satellite_models_have_shared_assets_and_valid_extended_orientations(
    globe_page: Any,
) -> None:
    original = globe_page.evaluate("JSON.stringify(state.referenceData)")
    for time in [-2 * 86400, 0, 43200, 3 * 86400]:
        globe_page.evaluate("time => setReplayTime(time, true)", time)
        globe_page.wait_for_function("state.globe.dataSourceDisplay.ready")
        models = globe_page.evaluate("""() => {
          const viewer = state.globe, now = viewer.clock.currentTime;
          return viewer.entities.values.filter(e => e.model).map(e => {
            const position = e.position.getValue(now), q = e.orientation.getValue(now);
            const rotation = Cesium.Matrix3.fromQuaternion(q);
            const up = Cesium.Matrix3.getColumn(rotation, 2, new Cesium.Cartesian3());
            const radial = Cesium.Cartesian3.normalize(position, new Cesium.Cartesian3());
            return {id:e.id, uri:e.model.uri.getValue(),
              scale:e.model.scale.getValue(), cap:e.model.maximumScale.getValue(),
              orientation:Math.hypot(q.x,q.y,q.z,q.w),
              nadir:Cesium.Cartesian3.dot(up,radial),
              billboard:Boolean(e.billboard)};
          });
        }""")
        assert len(models) == 20
        assert len({model["uri"] for model in models}) == 1
        for model in models:
            assert model["scale"] == 1 and model["cap"] == 120000
            assert not model["billboard"]
            assert model["orientation"] == pytest.approx(1)
            assert model["nadir"] > 0.99
    assert globe_page.evaluate("JSON.stringify(state.referenceData)") == original


def test_real_globe_has_startup_tracks_models_and_unmodified_source_positions(
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
            model:satellite.model.uri.getValue(), billboard:Boolean(satellite.billboard),
            orientation:Boolean(satellite.orientation.getValue(viewer.clock.currentTime)),
            pixels:satellite.model.minimumPixelSize.getValue()};
        })
      };
    }""")
    assert scene["satellites"] == 20
    assert scene["targets"] == 500
    for orbit in scene["paths"]:
        assert orbit["future"] == pytest.approx(orbit["period"] / 2)
        assert orbit["futureShown"] and orbit["pastShown"]
        assert orbit["model"] == "./models/earth-observer.glb?v=0.15.0"
        assert not orbit["billboard"] and orbit["orientation"]
        assert orbit["pixels"] in {28, 40}
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


@pytest.mark.parametrize("projection", ["3d", "2d", "2.5d"])
def test_compass_tracks_screen_north_with_upright_n_and_resets_without_moving_the_camera(
    globe_page: Any, projection: str
) -> None:
    if projection != "3d":
        globe_page.evaluate("mode => setMapViewMode(mode)", projection)
        globe_page.wait_for_function(
            "mode => state.viewMode === mode && !state.viewTransition", arg=projection
        )
    globe_page.evaluate("""() => {
      const viewer = state.globe;
      // Keep the tilted view within the map bounds, away from Cesium's native
      // off-map inertia/correction, so we can isolate the reset control itself.
      const planar = state.viewMode === '2.5d';
      viewer.camera.setView({destination:planar ? new Cesium.Cartesian3(0,0,8000000) : undefined,
        convert:!planar, orientation:{heading:Cesium.Math.toRadians(260),
        pitch:planar ? Cesium.Math.toRadians(-55) : viewer.camera.pitch, roll:0}});
      viewer.scene.requestRender();
    }""")
    globe_page.wait_for_timeout(150)
    bearing = globe_page.evaluate(SCREEN_NORTH_BEARING)
    assert_compass_matches_screen_north(globe_page)
    assert globe_page.locator("#camera-heading, #north-view small").count() == 0
    assert globe_page.locator("#north-view").get_attribute("title") == "Face north"
    assert (
        globe_page.locator("#north-view").get_attribute("aria-label")
        == f"Face north, current heading {int(bearing + 0.5) % 360}°"
    )
    compass = globe_page.evaluate("""() => {
      const dial = document.querySelector('.compass-dial');
      const n = document.querySelector('.compass-north-label');
      const matrix = n.getCTM();
      return {heading:document.getElementById('north-view').dataset.heading,
        rose:document.querySelector('.compass-rose').getAttribute('transform'),
        label:n.getAttribute('transform'), upright:Math.atan2(matrix.b,matrix.a),
        size:Math.min(dial.clientWidth,dial.clientHeight)};
    }""")
    assert float(compass["heading"]) == pytest.approx(bearing, abs=0.006)
    assert compass["rose"] == f"rotate({-float(compass['heading']):g} 24 24)"
    assert compass["label"] == f"rotate({compass['heading']} 24 9)"
    assert compass["upright"] == pytest.approx(0, abs=1e-10)
    assert compass["size"] == 48
    before = globe_page.evaluate("""() => ({position:state.globe.camera.positionWC,
      pitch:state.globe.camera.pitch,time:state.replay.time,source:JSON.stringify(state.currentPayload)})""")
    globe_page.locator("#north-view").focus()
    globe_page.keyboard.press("Enter")
    globe_page.wait_for_function(
        "Number(document.getElementById('north-view').dataset.heading) % 360 === 0"
    )
    after = globe_page.evaluate("""() => ({position:state.globe.camera.positionWC,
      pitch:state.globe.camera.pitch,time:state.replay.time,source:JSON.stringify(state.currentPayload)})""")
    for axis in ["x", "y", "z"]:
        assert after["position"][axis] == pytest.approx(before["position"][axis], abs=0.001)
    assert after["pitch"] == pytest.approx(before["pitch"], abs=1e-10)
    assert after["time"] == before["time"]
    assert after["source"] == before["source"]
    assert_single_screen(globe_page)


@pytest.mark.parametrize(
    ("mode", "viewport"),
    [("overview", (1440, 900)), ("overview", (375, 667)), ("follow", (1440, 900))],
)
def test_compass_tracks_tilted_screen_roll_without_a_heading_change(
    globe_page: Any, mode: str, viewport: tuple[int, int]
) -> None:
    globe_page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
    globe_page.wait_for_timeout(150)
    if mode == "follow":
        globe_page.locator("#camera-follow").click()
        globe_page.wait_for_function("state.globe.trackedEntity && state.cameraMode === 'follow'")
        globe_page.wait_for_timeout(150)
    source = globe_page.evaluate("JSON.stringify(state.currentPayload)")
    globe_page.evaluate("""() => {
      state.globe.camera.setView({orientation:{heading:0,pitch:Cesium.Math.toRadians(-55),roll:0}});
      state.globe.scene.requestRender();
    }""")
    globe_page.wait_for_timeout(150)
    original = globe_page.evaluate("""() => ({heading:state.globe.camera.heading,
      position:Cesium.Cartesian3.clone(state.globe.camera.positionWC),time:state.replay.time,
      north:document.getElementById('north-view').dataset.heading})""")
    for angle in [45, -90, 180]:
        globe_page.evaluate(
            """angle => {
          state.globe.camera.look(state.globe.camera.direction,Cesium.Math.toRadians(angle));
          state.globe.scene.requestRender();
        }""",
            angle,
        )
        globe_page.wait_for_timeout(150)
        assert_compass_matches_screen_north(globe_page)
        difference = globe_page.evaluate(
            "heading => Math.atan2(Math.sin(state.globe.camera.heading-heading),"
            "Math.cos(state.globe.camera.heading-heading))",
            original["heading"],
        )
        assert difference == pytest.approx(0, abs=1e-7)
        assert globe_page.locator("#north-view").get_attribute("data-heading") != original["north"]
    assert globe_page.evaluate("state.cameraMode") == mode
    assert globe_page.evaluate("state.replay.time") == original["time"]
    assert globe_page.evaluate("JSON.stringify(state.currentPayload)") == source
    assert globe_page.evaluate(
        "position => Cesium.Cartesian3.distance(position,state.globe.camera.positionWC)",
        original["position"],
    ) < (0.01 if mode == "follow" else 0.001)
    assert_single_screen(globe_page)


@pytest.mark.parametrize(("projection", "mode"), [("3d", "overview"), ("2.5d", "overview")])
def test_compass_tracks_subthreshold_roll_while_replay_is_paused(
    globe_page: Any, projection: str, mode: str
) -> None:
    if projection != "3d":
        globe_page.evaluate("mode => setMapViewMode(mode)", projection)
        globe_page.wait_for_function("!state.viewTransition")
    globe_page.wait_for_timeout(200)
    globe_page.evaluate("""() => {
      window.smallTurnEvents = 0;
      state.globe.camera.changed.addEventListener(() => smallTurnEvents++);
    }""")
    previous = globe_page.locator("#north-view").get_attribute("data-heading")
    globe_page.evaluate("""() => {
      state.globe.camera.look(state.globe.camera.direction,Cesium.Math.toRadians(0.1));
      state.globe.scene.requestRender();
    }""")
    globe_page.wait_for_timeout(150)
    assert globe_page.evaluate("smallTurnEvents") == 0
    assert_compass_matches_screen_north(globe_page)
    assert globe_page.locator("#north-view").get_attribute("data-heading") != previous
    assert globe_page.evaluate("!state.replay.playing && state.replay.time === 0")
    assert globe_page.evaluate("state.cameraMode") == mode


@pytest.mark.parametrize("mode", ["overview", "follow"])
def test_compass_stays_aligned_during_real_mouse_camera_rotation(
    globe_page: Any, mode: str
) -> None:
    if mode == "follow":
        globe_page.locator("#camera-follow").click()
        globe_page.wait_for_function("state.globe.trackedEntity && state.cameraMode === 'follow'")
        globe_page.wait_for_timeout(150)
    before = globe_page.evaluate("""() => ({
      right:Cesium.Cartesian3.clone(state.globe.camera.rightWC),
      source:JSON.stringify(state.currentPayload),time:state.replay.time})""")
    box = globe_page.locator("#mission-globe").bounding_box()
    x, y = box["x"] + box["width"] * 0.55, box["y"] + box["height"] * 0.5
    globe_page.mouse.move(x, y)
    globe_page.mouse.down(button="middle")
    try:
        for dx, dy in [(35, 5), (65, 15), (100, 25)]:
            globe_page.mouse.move(x + dx, y + dy, steps=10)
            globe_page.wait_for_timeout(100)
            assert_compass_matches_screen_north(globe_page)
    finally:
        globe_page.mouse.up(button="middle")
    after = globe_page.evaluate("Cesium.Cartesian3.clone(state.globe.camera.rightWC)")
    assert after != before["right"]
    assert globe_page.evaluate("state.cameraMode") == mode
    assert globe_page.evaluate("state.replay.time") == before["time"]
    assert globe_page.evaluate("JSON.stringify(state.currentPayload)") == before["source"]
    assert_single_screen(globe_page)


def test_compass_retains_last_valid_bearing_when_north_is_parallel_to_view_ray(
    globe_page: Any,
) -> None:
    globe_page.evaluate("""() => {
      state.globe.camera.setView({orientation:{heading:Cesium.Math.toRadians(45),
        pitch:Cesium.Math.toRadians(-55),roll:0}});
      state.globe.scene.requestRender();
    }""")
    globe_page.wait_for_timeout(150)
    assert_compass_matches_screen_north(globe_page)
    previous = globe_page.locator("#north-view").evaluate("node => node.outerHTML")
    globe_page.evaluate("""() => {
      const camera = state.globe.camera;
      const surface = Cesium.Ellipsoid.WGS84.scaleToGeodeticSurface(camera.positionWC);
      const frame = Cesium.Transforms.eastNorthUpToFixedFrame(surface);
      camera.setView({orientation:{direction:Cesium.Matrix4.multiplyByPointAsVector(
        frame,Cesium.Cartesian3.UNIT_Y,new Cesium.Cartesian3()),
        up:Cesium.Matrix4.multiplyByPointAsVector(
          frame,Cesium.Cartesian3.UNIT_Z,new Cesium.Cartesian3())}});
      state.globe.scene.requestRender();
    }""")
    globe_page.wait_for_timeout(150)
    assert globe_page.locator("#north-view").evaluate("node => node.outerHTML") == previous
    globe_page.locator("#camera-overview").click()
    globe_page.wait_for_timeout(750)
    assert_compass_matches_screen_north(globe_page)


def test_compass_frame_listener_is_not_duplicated_by_plan_reloads(globe_page: Any) -> None:
    listeners = globe_page.evaluate("state.globe.scene.postRender.numberOfListeners")
    for plan in ["eos-sa-profit", "eos-greedy-profit", "eos-sa-balanced"]:
        globe_page.evaluate(
            """id => {
          renderResult(OrbitReplay.referencePayload(state.referenceData,
            state.referenceData.plans.find(plan => plan.plan_id === id)));
        }""",
            plan,
        )
        globe_page.wait_for_timeout(150)
        assert globe_page.evaluate("state.globe.scene.postRender.numberOfListeners") == listeners
        assert_compass_matches_screen_north(globe_page)


@pytest.mark.parametrize("viewport", [(1440, 900), (800, 600), (375, 667)])
def test_camera_toolbar_is_compact_and_keeps_keyboard_follow_and_overview(
    globe_page: Any, viewport: tuple[int, int]
) -> None:
    width, height = viewport
    globe_page.set_viewport_size({"width": width, "height": height})
    globe_page.wait_for_timeout(150)
    source = globe_page.evaluate("JSON.stringify(state.currentPayload)")
    time = globe_page.evaluate("state.replay.time")
    group = globe_page.get_by_role("group", name="Satellite camera controls", exact=True)
    assert group.get_by_role("button", name="Overview", exact=True).count() == 1
    assert group.get_by_role("button", name="Follow", exact=True).count() == 1
    assert group.locator("button svg[aria-hidden='true']").count() == 2
    assert globe_page.evaluate("""() => {
      const toolbar = document.querySelector('.viewport-toolbar').getBoundingClientRect();
      const group = document.querySelector('.orbit-camera').getBoundingClientRect();
      const frame = document.querySelector('.globe-frame').getBoundingClientRect();
      const playback = document.querySelector('.replay-bar').getBoundingClientRect();
      const expand = document.getElementById('expand-map').getBoundingClientRect();
      return group.bottom <= frame.top && Math.abs(frame.bottom - playback.top) < 1
        && group.left > expand.right && group.width <= 180 && group.left >= toolbar.left
        && group.right <= toolbar.right && group.top >= toolbar.top
        && group.bottom <= toolbar.bottom
        && [...document.querySelectorAll('.orbit-camera button')].every(button => {
          const box = button.getBoundingClientRect();
          return getComputedStyle(button).borderTopWidth === '0px'
            && box.height >= 28 && box.left >= group.left && box.right <= group.right;
        });
    }""")
    assert globe_page.locator("#camera-overview").get_attribute("aria-pressed") == "true"
    globe_page.locator("#camera-follow").focus()
    globe_page.keyboard.press("Enter")
    globe_page.wait_for_function("state.cameraMode === 'follow' && state.globe.trackedEntity")
    assert globe_page.locator("#camera-follow").get_attribute("aria-pressed") == "true"
    assert globe_page.locator("#camera-follow").get_attribute("title") == "Stop following satellite"
    assert globe_page.locator("#camera-overview").get_attribute("aria-pressed") == "false"
    globe_page.keyboard.press("Enter")
    assert globe_page.evaluate("state.cameraMode === 'manual' && !state.globe.trackedEntity")
    assert globe_page.locator("#camera-follow").get_attribute("aria-pressed") == "false"
    assert (
        globe_page.locator("#camera-follow").get_attribute("title") == "Follow selected satellite"
    )
    globe_page.locator("#camera-overview").focus()
    globe_page.keyboard.press("Enter")
    assert globe_page.locator("#camera-overview").get_attribute("aria-pressed") == "true"
    assert globe_page.evaluate("state.replay.time") == time
    assert globe_page.evaluate("JSON.stringify(state.currentPayload)") == source
    assert_single_screen(globe_page)


def test_compass_north_reset_releases_satellite_follow(globe_page: Any) -> None:
    globe_page.locator("#camera-follow").click()
    globe_page.wait_for_function("state.globe.trackedEntity && state.cameraMode === 'follow'")
    globe_page.locator("#north-view").click()
    globe_page.wait_for_function(
        "Number(document.getElementById('north-view').dataset.heading) % 360 === 0"
    )
    assert globe_page.evaluate(
        "state.globe.trackedEntity === undefined && state.cameraMode === 'manual'"
    )
    assert globe_page.locator("#camera-follow").get_attribute("aria-pressed") == "false"


def test_compass_north_reset_interrupts_a_camera_flight_and_freezes_during_morph(
    globe_page: Any,
) -> None:
    globe_page.evaluate("""() => {
      const compass = document.getElementById('north-view');
      const snapshot = compass.outerHTML;
      state.viewTransition = true;
      updateCameraCompass();
      window.frozenCompass = compass.outerHTML === snapshot;
      state.viewTransition = false;
      window.flightCancelled = false;
      state.globe.camera.flyTo({destination:Cesium.Cartesian3.fromDegrees(35,0,12000000),
        orientation:{heading:Cesium.Math.toRadians(150),pitch:Cesium.Math.toRadians(-65),roll:0},
        duration:3,cancel:() => {window.flightCancelled = true;}});
    }""")
    assert globe_page.evaluate("frozenCompass")
    globe_page.wait_for_function(
        "Number(document.getElementById('north-view').dataset.heading) > 1"
    )
    globe_page.locator("#north-view").click()
    assert globe_page.evaluate("flightCancelled")
    globe_page.wait_for_function(
        "Number(document.getElementById('north-view').dataset.heading) % 360 === 0"
    )
    position = globe_page.evaluate("Cesium.Cartesian3.clone(state.globe.camera.positionWC)")
    globe_page.wait_for_timeout(750)
    assert globe_page.locator("#camera-heading").count() == 0
    assert (
        globe_page.evaluate("Number(document.getElementById('north-view').dataset.heading) % 360")
        == 0
    )
    assert (
        globe_page.evaluate(
            "position => Cesium.Cartesian3.distance(position,state.globe.camera.positionWC)",
            position,
        )
        < 0.001
    )


def test_map_information_control_is_hidden_and_preserves_native_provider_credits(
    globe_page: Any,
) -> None:
    globe_page.wait_for_function(
        "elements.globe.dataset.imagerySource === 'natural-earth-fallback'"
    )
    credit = globe_page.locator(".cesium-credit-expand-link")
    assert credit.is_hidden()
    assert credit.get_attribute("hidden") == ""
    assert credit.get_attribute("tabindex") == "-1"
    assert credit.locator("svg").count() == 0
    assert (
        globe_page.locator(".attribution-icon, #comparison-info, #comparison-scales").count() == 0
    )
    assert globe_page.get_by_text("Data attribution", exact=True).is_hidden()
    assert globe_page.locator(".cesium-credit-logoContainer img").is_visible()
    assert globe_page.locator(".masthead").inner_text().find("Mission workspace") == -1
    # Inspect native credit content programmatically: the hidden control has no UI entry.
    credit.evaluate("node => node.click()")
    popup = globe_page.locator(".cesium-credit-lightbox")
    assert popup.is_visible()
    assert "Natural Earth II" in popup.inner_text()
    globe_page.locator(".cesium-credit-lightbox-close").click()
    assert popup.is_hidden()
    globe_page.locator("#solver-select").select_option("eos-sa-profit")
    globe_page.wait_for_function("!state.busy && state.globe.dataSourceDisplay.ready")
    assert credit.is_hidden()
    assert credit.locator("svg").count() == 0
    credit.evaluate("node => node.click()")
    assert "Natural Earth II" in globe_page.locator(".cesium-credit-lightbox").inner_text()
    globe_page.locator(".cesium-credit-lightbox-close").click()
    globe_page.emulate_media(reduced_motion="reduce")
    for selector in ["#view-2d", "#view-2_5d", "#view-3d"]:
        globe_page.locator(selector).click()
        assert credit.is_hidden()
        assert globe_page.locator(".cesium-credit-logoContainer img").is_visible()
    assert_single_screen(globe_page)


@pytest.mark.parametrize("viewport", [(390, 844), (375, 667)])
def test_compact_map_keeps_compass_and_credits_inside_and_camera_controls_outside(
    globe_page: Any, viewport: tuple[int, int]
) -> None:
    width, height = viewport
    globe_page.set_viewport_size({"width": width, "height": height})
    globe_page.wait_for_timeout(200)
    assert globe_page.evaluate("""() => {
      const frame = document.querySelector('.globe-frame').getBoundingClientRect();
      const compass = document.getElementById('north-view').getBoundingClientRect();
      const controls = document.querySelector('.orbit-camera').getBoundingClientRect();
      const credit = document.querySelector('.cesium-credit-logoContainer').getBoundingClientRect();
      const legend = document.querySelector('.globe-overlay').getBoundingClientRect();
      return compass.width >= 44 && compass.height >= 44 && compass.right < frame.right
        && compass.bottom < frame.bottom && compass.top >= frame.top
        && controls.bottom <= frame.top && credit.top >= frame.top && credit.bottom <= frame.bottom
        && compass.top >= legend.bottom + 6;
    }""")
    assert_single_screen(globe_page)


def test_all_twenty_cone_tips_track_native_satellites_with_a_full_30_degree_fov(
    globe_page: Any,
) -> None:
    globe_page.wait_for_function(
        "[...state.sensorFovs.values()].every(s => s.solid.ready && s.wire.ready)"
    )
    source = globe_page.evaluate("JSON.stringify(state.currentPayload)")
    assert globe_page.evaluate("state.fovPrimitives.length") == 40
    assert globe_page.evaluate("state.sensorFovs.size") == 20
    assert globe_page.evaluate("""() => {
      const sensor = [...state.sensorFovs.values()][0];
      const frame = sensor.frame, hierarchy = sensor.footprint.polygon.hierarchy.getValue();
      updateReplayVisuals();
      return sensor.frame === frame && sensor.footprint.polygon.hierarchy.isConstant
        && sensor.footprint.polygon.hierarchy.getValue() === hierarchy;
    }""")
    for time in [-86400, 0, 3600, 43200, 43201, 3 * 86400]:
        globe_page.evaluate("time => setReplayTime(time, true)", time)
        geometry = globe_page.evaluate("""() => [...state.sensorFovs].map(([id, sensor]) => {
          const Cesium = window.Cesium, matrix = sensor.solid.modelMatrix;
          const origin = state.orbitPositions.get(id).getValue(state.globe.clock.currentTime);
          const tip = Cesium.Matrix4.multiplyByPoint(matrix,new Cesium.Cartesian3(0,0,.5),
            new Cesium.Cartesian3());
          const up = Cesium.Matrix4.multiplyByPointAsVector(matrix,Cesium.Cartesian3.UNIT_Z,
            new Cesium.Cartesian3());
          const radius = Cesium.Cartesian3.magnitude(Cesium.Matrix4.multiplyByPointAsVector(
            matrix,Cesium.Cartesian3.UNIT_X,new Cesium.Cartesian3()));
          const length = Cesium.Cartesian3.magnitude(up);
          const expected = Cesium.Cartesian3.normalize(origin,new Cesium.Cartesian3());
          Cesium.Cartesian3.normalize(up,up);
          return {tipError:Cesium.Cartesian3.distance(tip,origin),
            direction:Cesium.Cartesian3.dot(up,expected),
            angle:2*Math.atan(radius/length)*180/Math.PI, length,
            alpha:sensor.solid.getGeometryInstanceAttributes('sensor-'+id).color[3]/255,
            pickable:sensor.solid.allowPicking || sensor.wire.allowPicking,
            outline:sensor.footprint.polygon.hierarchy.getValue().positions.length};
        })""")
        for cone in geometry:
            assert cone["tipError"] < 1e-7, cone
            assert cone["direction"] == pytest.approx(1, abs=1e-12), cone
            assert cone["angle"] == pytest.approx(30, abs=1e-10), cone
            assert 300000 < cone["length"] < 2000000, cone
            assert 0.03 <= cone["alpha"] <= 0.04, cone
            assert not cone["pickable"] and cone["outline"] == 48, cone
    assert globe_page.evaluate("JSON.stringify(state.currentPayload)") == source
    assert (
        globe_page.evaluate("state.globe.entities.values.filter(e=>e.id.startsWith('ray-')).length")
        == 0
    )


@pytest.mark.parametrize("projection", ["3d", "2d", "2.5d"])
def test_fov_layers_use_native_cones_and_projected_footprints_without_resetting_time(
    globe_page: Any, projection: str
) -> None:
    globe_page.evaluate("setReplayTime(-86400, true)")
    if projection != "3d":
        globe_page.evaluate("mode => setMapViewMode(mode)", projection)
        globe_page.wait_for_function(
            "mode => state.viewMode === mode && !state.viewTransition", arg=projection
        )
    assert globe_page.evaluate("state.replay.time") == -86400
    assert globe_page.evaluate("state.fovPrimitives.show") == (projection == "3d")
    assert globe_page.evaluate("[...state.sensorFovs.values()].every(s=>s.footprint.show)")
    globe_page.locator("#toggle-layers").click()
    globe_page.locator("#toggle-fov").click()
    assert not globe_page.evaluate("state.fovPrimitives.show")
    assert globe_page.evaluate("[...state.sensorFovs.values()].every(s=>!s.footprint.show)")
    globe_page.locator("#toggle-fov").click()
    assert globe_page.evaluate("state.fovPrimitives.show") == (projection == "3d")
    assert globe_page.evaluate("[...state.sensorFovs.values()].every(s=>s.footprint.show)")
    globe_page.keyboard.press("Escape")
    assert globe_page.evaluate("state.replay.time") == -86400
    assert_single_screen(globe_page)


def test_plan_reload_disposes_previous_cones_instead_of_accumulating_primitives(
    globe_page: Any,
) -> None:
    for plan in ["eos-sa-profit", "eos-greedy-profit", "eos-sa-balanced"]:
        assert globe_page.evaluate(
            """id => {
          const previous = state.fovPrimitives;
          const plan = state.referenceData.plans.find(p => p.plan_id === id);
          renderResult(OrbitReplay.referencePayload(state.referenceData, plan));
          return previous.isDestroyed() && !state.globe.scene.primitives.contains(previous);
        }""",
            plan,
        )
        assert globe_page.evaluate("state.sensorFovs.size") == 20
        assert globe_page.evaluate("state.fovPrimitives.length") == 40
        assert (
            globe_page.evaluate(
                "state.globe.entities.values.filter(e=>e.id.startsWith('fov-')).length"
            )
            == 20
        )
        globe_page.wait_for_function("state.globe.dataSourceDisplay.ready")


@pytest.mark.parametrize("projection", ["3d", "2d", "2.5d"])
def test_geographic_grid_is_transparent_and_does_not_add_mission_entities(
    globe_page: Any, projection: str
) -> None:
    if projection != "3d":
        globe_page.evaluate("mode => setMapViewMode(mode)", projection)
        globe_page.wait_for_function(
            "mode => state.viewMode === mode && !state.viewTransition", arg=projection
        )
    source = globe_page.evaluate("JSON.stringify(state.currentPayload)")
    grid = globe_page.evaluate("""async () => {
      const viewer = state.globe, layer = viewer.imageryLayers.get(2);
      const provider = layer.imageryProvider;
      const canvas = await provider.requestImage(0,0,0);
      const pixels = canvas.getContext('2d');
      return {count:viewer.imageryLayers.length,
        native:provider instanceof Cesium.GridImageryProvider,
        geographic:provider.tilingScheme instanceof Cesium.GeographicTilingScheme,
        alpha:provider.hasAlphaChannel,
        empty:[...pixels.getImageData(10,10,1,1).data],
        line:[...pixels.getImageData(0,0,1,1).data],
        satellites:viewer.entities.values.filter(e=>e.id.startsWith('satellite-')).length,
        targets:viewer.entities.values.filter(e=>e.id.startsWith('target-')).length};
    }""")
    assert grid["count"] == 3
    assert grid["native"] and grid["geographic"] and grid["alpha"]
    assert grid["empty"][3] == 0
    assert 0 < grid["line"][3] < 128
    assert grid["line"][0] < grid["line"][2]
    assert grid["satellites"] == 20 and grid["targets"] == 500
    assert globe_page.evaluate("JSON.stringify(state.currentPayload)") == source
    assert_single_screen(globe_page)


@pytest.mark.parametrize("projection", ["3d", "2d", "2.5d"])
def test_extended_orbits_keep_native_positions_paths_and_follow_in_all_views(
    globe_page: Any, projection: str
) -> None:
    if projection != "3d":
        globe_page.evaluate("mode => setMapViewMode(mode)", projection)
        globe_page.wait_for_function(
            "mode => state.viewMode === mode && !state.viewTransition", arg=projection
        )
    initial = globe_page.evaluate("JSON.stringify(state.currentPayload)")
    for time in [-3 * 86400, -1, 43200, 43201, 3 * 86400]:
        globe_page.evaluate("time => setReplayTime(time, true)", time)
        errors = globe_page.evaluate("""() => state.currentPayload.replay.orbits.map(orbit => {
          const model = state.orbitModels.get(orbit.satellite_id);
          const position = state.orbitPositions.get(orbit.satellite_id)
            .getValue(state.globe.clock.currentTime);
          const expected = Cesium.Cartesian3.fromArray(model.cartesian(state.replay.time));
          return position ? Cesium.Cartesian3.distance(position,expected) : Infinity;
        })""")
        assert all(error < 1e-5 for error in errors), errors
        assert globe_page.evaluate("state.replay.time") == time
        assert globe_page.evaluate("state.globe.clock.clockRange === Cesium.ClockRange.UNBOUNDED")
        assert (
            globe_page.evaluate(
                "state.globe.entities.values.filter(e=>e.id.startsWith('ray-')).length"
            )
            == 0
        )
        assert globe_page.locator("#selected-state").text_content() != "Observing"
        globe_page.wait_for_function("state.globe.dataSourceDisplay.ready")
        assert globe_page.evaluate("JSON.stringify(state.currentPayload)") == initial
    globe_page.locator("#camera-follow").click()
    globe_page.evaluate("setReplayTime(4*86400, true)")
    globe_page.wait_for_timeout(200)
    assert globe_page.evaluate("state.cameraMode") == "follow"
    assert globe_page.locator("#orbit-basis").is_visible()
    assert globe_page.evaluate("state.globe.entities.values.length") == 580
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    globe_page.screenshot(path=str(SCREENSHOTS / f"extended-orbit-{projection}.png"))
    assert_single_screen(globe_page)


def test_native_starfield_loads_and_renders_behind_the_globe(globe_page: Any) -> None:
    assert globe_page.evaluate("state.globe.scene.skyBox.show")
    # Cesium 1.143 delegates skybox texture loading to CubeMapPanorama.
    globe_page.wait_for_function(
        "Boolean(state.globe.scene.skyBox._panorama._cubeMap)", timeout=30000
    )
    pixels = globe_page.evaluate("""() => {
      const viewer = state.globe;
      const sky = viewer.scene.skyBox;
      const render = show => {
        sky.show = show;
        viewer.scene.requestRender();
        viewer.render();
        return viewer.scene.context.readPixels({x:10, y:10, width:96, height:96});
      };
      const without = render(false), withStars = render(true);
      let changed = 0;
      for (let i = 0; i < withStars.length; i += 4) {
        if (withStars[i] !== without[i] || withStars[i+1] !== without[i+1]
            || withStars[i+2] !== without[i+2]) changed++;
      }
      return {changed, faces:Object.values(sky.sources)};
    }""")
    assert pixels["changed"] > 10, pixels
    assert len(pixels["faces"]) == 6
    assert all("/Assets/Textures/SkyBox/" in source for source in pixels["faces"])
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    globe_page.screenshot(path=str(SCREENSHOTS / "starfield-3d.png"))
    assert_single_screen(globe_page)


def test_solar_light_tracks_replay_utc_without_new_entities_or_boundary_geometry(
    globe_page: Any,
) -> None:
    source = globe_page.evaluate("JSON.stringify(state.currentPayload)")
    directions = []
    for time in [-86400, 0, 21600, 43200, 3 * 86400, 180 * 86400]:
        globe_page.evaluate("time => setReplayTime(time, true)", time)
        globe_page.wait_for_timeout(80)
        geometry = globe_page.evaluate("""() => {
          const viewer = state.globe;
          viewer.scene.requestRender();
          viewer.render();
          const direction = viewer.scene.context.uniformState.sunDirectionWC;
          const ephemeris = Cesium.Simon1994PlanetaryPositions;
          const inertial = ephemeris.computeSunPositionInEarthInertialFrame(
            viewer.clock.currentTime);
          const expected = Cesium.Matrix3.multiplyByVector(
            Cesium.Transforms.computeIcrfToCentralBodyFixedMatrix(viewer.clock.currentTime),
            inertial,new Cesium.Cartesian3());
          const epoch = Cesium.JulianDate.fromIso8601(state.currentPayload.scenario.epoch_utc);
          return {
            lighting:viewer.scene.globe.enableLighting, sun:viewer.scene.sun.show,
            clock:Cesium.JulianDate.secondsDifference(viewer.clock.currentTime,epoch),
            direction:[direction.x,direction.y,direction.z],
            match:Cesium.Cartesian3.dot(Cesium.Cartesian3.normalize(expected,expected),direction),
            distance:Cesium.Cartesian3.magnitude(inertial),
            fadeOut:viewer.scene.globe.lightingFadeOutDistance,
            fadeIn:viewer.scene.globe.lightingFadeInDistance,
            entities:viewer.entities.values.filter(e=>!e.id.startsWith('ray-')).length};
        }""")
        assert geometry["lighting"] and geometry["sun"]
        assert geometry["clock"] == time
        assert geometry["entities"] == 580
        assert geometry["match"] == pytest.approx(1, abs=1e-12)
        assert 1.45e11 < geometry["distance"] < 1.53e11
        assert geometry["fadeOut"] == 0 and geometry["fadeIn"] == 1
        directions.append(geometry["direction"])
    assert sum(a * b for a, b in zip(directions[1], directions[2], strict=True)) < 0.3
    assert globe_page.evaluate("JSON.stringify(state.currentPayload)") == source
    assert globe_page.locator("#sun-direction").count() == 0


@pytest.mark.parametrize("projection", ["2d", "2.5d"])
def test_flat_views_have_no_terminator_or_day_night_shading(
    globe_page: Any, projection: str
) -> None:
    globe_page.evaluate("setReplayTime(-86400, true)")
    globe_page.evaluate("mode => setMapViewMode(mode)", projection)
    globe_page.wait_for_function(
        "mode => state.viewMode === mode && !state.viewTransition", arg=projection
    )
    globe_page.wait_for_timeout(80)
    assert not globe_page.evaluate("state.globe.scene.globe.enableLighting")
    assert not globe_page.evaluate("state.globe.scene.sun.show")
    assert globe_page.locator("#sun-direction").count() == 0
    globe_page.locator("#toggle-layers").click()
    assert globe_page.locator("#toggle-illumination").is_disabled()
    assert globe_page.locator("#toggle-sat-labels").is_visible()
    globe_page.keyboard.press("Escape")
    assert globe_page.evaluate("state.replay.time") == -86400
    globe_page.evaluate("setMapViewMode('3d')")
    globe_page.wait_for_function("state.viewMode === '3d' && !state.viewTransition")
    globe_page.wait_for_timeout(80)
    assert globe_page.evaluate("state.globe.scene.globe.enableLighting")
    assert globe_page.evaluate("state.globe.scene.sun.show")
    assert globe_page.evaluate("state.replay.time") == -86400
    assert_single_screen(globe_page)


def test_solar_layer_setting_survives_reload_without_new_render_listeners(
    globe_page: Any,
) -> None:
    globe_page.locator("#toggle-layers").click()
    globe_page.locator("#toggle-illumination").click()
    assert not globe_page.evaluate("state.globe.scene.sun.show")
    assert globe_page.locator("#sun-direction").count() == 0
    globe_page.keyboard.press("Escape")
    globe_page.evaluate("() => { window.originalSun = state.globe.scene.sun; }")
    for plan in ["eos-sa-profit", "eos-greedy-profit", "eos-sa-balanced"]:
        assert globe_page.evaluate(
            """id => {
          const listeners = state.globe.scene.preRender.numberOfListeners;
          renderResult(OrbitReplay.referencePayload(state.referenceData,
            state.referenceData.plans.find(p => p.plan_id === id)));
          return state.globe.scene.sun === originalSun && !originalSun.show
            && !state.globe.scene.globe.enableLighting
            && state.globe.scene.preRender.numberOfListeners === listeners;
        }""",
            plan,
        )
    globe_page.locator("#toggle-layers").click()
    globe_page.locator("#toggle-illumination").click()
    globe_page.keyboard.press("Escape")
    assert globe_page.evaluate(
        "state.globe.scene.globe.enableLighting && state.globe.scene.sun.show"
    )


def test_day_night_and_sun_are_rendered_not_only_ui_flags(globe_page: Any) -> None:
    pixels = globe_page.evaluate("""() => {
      const viewer = state.globe, scene = viewer.scene;
      viewer.scene.requestRender();
      viewer.render();
      const sunPosition = Cesium.Cartesian3.clone(scene.context.uniformState.sunPositionWC);
      try {
        const night = enabled => {
          scene.globe.enableLighting = enabled;
          scene.requestRender();
          viewer.render();
          return scene.context.readPixels();
        };
        const unshaded = night(false), shaded = night(true);
        let nightPixels = 0;
        for (let i=0; i<unshaded.length; i+=4) {
          if (unshaded[i]+unshaded[i+1]+unshaded[i+2]
              > shaded[i]+shaded[i+1]+shaded[i+2]+15) nightPixels++;
        }
        const direction = Cesium.Cartesian3.normalize(Cesium.Cartesian3.subtract(
          sunPosition,viewer.camera.positionWC,new Cesium.Cartesian3()),
          new Cesium.Cartesian3());
        viewer.camera.setView({orientation:{direction,
          up:Cesium.Cartesian3.normalize(Cesium.Cartesian3.cross(viewer.camera.rightWC,direction,
            new Cesium.Cartesian3()),new Cesium.Cartesian3())}});
        const disc = show => {
          scene.sun.show = show;
          scene.requestRender();
          viewer.render();
          return scene.context.readPixels({x:Math.floor(viewer.canvas.width/2)-48,
            y:Math.floor(viewer.canvas.height/2)-48,width:96,height:96});
        };
        disc(true);
        const dark = disc(false), lit = disc(true);
        let sunPixels = 0;
        for (let i=0; i<dark.length; i+=4) {
          if (lit[i]+lit[i+1]+lit[i+2] > dark[i]+dark[i+1]+dark[i+2]+30) sunPixels++;
        }
        return {nightPixels, sunPixels};
      } finally {
        updateSolarEnvironment();
      }
    }""")
    assert pixels["nightPixels"] > 100, pixels
    assert pixels["sunPixels"] > 5, pixels
    assert globe_page.locator("#sun-direction").count() == 0


@pytest.mark.parametrize("projection", ["3d", "2d", "2.5d"])
def test_satellite_controls_stay_outside_the_map_after_projection_and_expansion(
    globe_page: Any, projection: str
) -> None:
    globe_page.evaluate("setReplayTime(3600, true)")
    if projection != "3d":
        globe_page.evaluate("mode => setMapViewMode(mode)", projection)
        globe_page.wait_for_function(
            "mode => state.viewMode === mode && !state.viewTransition", arg=projection
        )
    assert globe_page.locator(".globe-frame .orbit-camera").count() == 0
    assert globe_page.locator(".viewport-tools .orbit-camera").count() == 1
    assert globe_page.locator("#orbit-hud").is_hidden()
    source = globe_page.evaluate("JSON.stringify(state.currentPayload)")
    selection = globe_page.evaluate("state.selectedSatelliteId")
    for expanded in [False, True, False]:
        if expanded != (globe_page.locator("#expand-map").get_attribute("aria-expanded") == "true"):
            globe_page.locator("#expand-map").click()
            globe_page.wait_for_timeout(100)
        assert globe_page.evaluate("""() => {
          const map = document.querySelector('.globe-frame').getBoundingClientRect();
          const controls = document.querySelector('.viewport-toolbar').getBoundingClientRect();
          const replay = document.querySelector('.replay-bar').getBoundingClientRect();
          return map.height > 0 && controls.bottom <= map.top
            && Math.abs(map.bottom - replay.top) < 1
            && [...document.querySelectorAll('.orbit-camera button')].every(button => {
              const box = button.getBoundingClientRect();
              return box.top >= controls.top && box.bottom <= controls.bottom;
            });
        }""")
        assert globe_page.evaluate("state.replay.time") == 3600
        assert globe_page.evaluate("state.selectedSatelliteId") == selection
        assert globe_page.evaluate("JSON.stringify(state.currentPayload)") == source
        assert_single_screen(globe_page)


def pickable_satellite(globe_page: Any) -> dict[str, Any]:
    return globe_page.wait_for_function(
        """() => {
      const viewer = state.globe;
      const box = elements.globe.getBoundingClientRect();
      const occluder = new Cesium.EllipsoidalOccluder(
        Cesium.Ellipsoid.WGS84, viewer.camera.positionWC);
      for (const entity of viewer.entities.values.filter(e => e.id.startsWith('satellite-'))) {
        const position = entity.position.getValue(viewer.clock.currentTime);
        if (state.viewMode === '3d' && !occluder.isPointVisible(position)) continue;
        const point = Cesium.SceneTransforms.worldToWindowCoordinates(viewer.scene, position);
        if (!point || point.x < 30 || point.x > box.width - 30
            || point.y < 30 || point.y > box.height - 30) continue;
        const x = box.left + point.x, y = box.top + point.y;
        if (document.elementFromPoint(x, y) !== viewer.canvas) continue;
        if (pickedMissionObject(viewer, point)?.id !== entity.id.slice(10)) continue;
        return {id:entity.id.slice(10), x, y};
      }
      return null; // Models become pickable after their first rendered frame.
    }""",
        timeout=10000,
    ).json_value()


@pytest.mark.parametrize("projection", ["3d", "2d", "2.5d"])
def test_satellite_popup_is_on_demand_translucent_and_dismissible(
    globe_page: Any, projection: str
) -> None:
    if projection != "3d":
        globe_page.evaluate("mode => setMapViewMode(mode)", projection)
        globe_page.wait_for_function(
            "mode => state.viewMode === mode && !state.viewTransition", arg=projection
        )
    popup = globe_page.get_by_role("region", name="Satellite details")
    assert globe_page.locator("#orbit-hud").is_hidden()
    source = globe_page.evaluate("JSON.stringify(state.currentPayload)")
    time = globe_page.evaluate("state.replay.time")
    height = globe_page.locator(".globe-frame").bounding_box()["height"]
    camera = globe_page.evaluate("Cesium.Cartesian3.clone(state.globe.camera.positionWC)")
    candidate = pickable_satellite(globe_page)
    globe_page.mouse.click(candidate["x"], candidate["y"])
    assert popup.is_visible()
    metadata = globe_page.evaluate("""() => {
      const orbit = state.currentPayload.replay.orbits.find(
        orbit => orbit.satellite_id === state.selectedSatelliteId);
      const position = state.orbitPositions.get(orbit.satellite_id)
        .getValue(state.globe.clock.currentTime);
      return {name:satelliteName(orbit.satellite_id),
        altitude:(Cesium.Cartographic.fromCartesian(position).height / 1000).toFixed(1) + ' km',
        period:(orbit.period_s / 60).toFixed(1) + ' min'};
    }""")
    assert globe_page.locator("#satellite-name").inner_text() == metadata["name"]
    assert globe_page.locator("#satellite-altitude").inner_text() == metadata["altitude"]
    assert globe_page.locator("#satellite-period").inner_text() == metadata["period"]
    assert popup.evaluate("""node => {
      const style = getComputedStyle(node), box = node.getBoundingClientRect();
      const map = elements.globe.getBoundingClientRect();
      const alpha = Number(style.backgroundColor.match(/[0-9.]+/g).at(-1));
      return style.position === 'absolute' && alpha > 0 && alpha < 1
        && style.backdropFilter.includes('blur')
        && box.left >= map.left && box.right <= map.right
        && box.top >= map.top && box.bottom <= map.bottom;
    }""")
    assert globe_page.locator(".globe-frame").bounding_box()["height"] == height
    assert globe_page.evaluate("Cesium.Cartesian3.clone(state.globe.camera.positionWC)") == camera
    assert globe_page.evaluate("state.replay.time") == time
    assert globe_page.evaluate("JSON.stringify(state.currentPayload)") == source
    globe_page.keyboard.press("Escape")
    assert globe_page.locator("#orbit-hud").is_hidden()
    globe_page.mouse.click(candidate["x"], candidate["y"])
    assert popup.is_visible()
    globe_page.get_by_role("button", name="Close satellite details").click()
    assert globe_page.locator("#orbit-hud").is_hidden()
    globe_page.mouse.click(candidate["x"], candidate["y"])
    blank = globe_page.evaluate("""() => {
      const viewer = state.globe, box = elements.globe.getBoundingClientRect();
      for (let y=30; y<box.height-30; y+=30) for (let x=30; x<box.width-30; x+=30) {
        if (document.elementFromPoint(box.left+x,box.top+y) === viewer.canvas
            && !pickedMissionObject(viewer,new Cesium.Cartesian2(x,y))) {
          return {x:box.left+x,y:box.top+y};
        }
      }
    }""")
    assert blank
    globe_page.mouse.click(blank["x"], blank["y"])
    assert globe_page.locator("#orbit-hud").is_hidden()
    assert globe_page.evaluate("state.selectedSatelliteId") == candidate["id"]
    assert_single_screen(globe_page)


@pytest.mark.parametrize("viewport", [(1440, 900), (375, 667)])
def test_satellite_canvas_picking_double_click_focus_follow_and_source_horizon(
    globe_page: Any, viewport: tuple[int, int]
) -> None:
    globe_page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
    globe_page.wait_for_timeout(200)
    candidate = pickable_satellite(globe_page)
    globe_page.mouse.move(candidate["x"], candidate["y"])
    globe_page.wait_for_function("!document.getElementById('globe-hover').hidden")
    globe_page.mouse.click(candidate["x"], candidate["y"])
    assert globe_page.locator("#orbit-hud").is_visible()
    assert globe_page.evaluate(
        "point => document.elementFromPoint(point.x,point.y) === state.globe.canvas", candidate
    )
    assert globe_page.locator("#satellite-name").get_attribute("title") == candidate["id"]
    assert globe_page.locator("#camera-focus").count() == 0
    before_selection = globe_page.evaluate("Cesium.Cartesian3.clone(state.globe.camera.positionWC)")
    globe_page.mouse.dblclick(candidate["x"], candidate["y"])
    globe_page.wait_for_timeout(750)
    assert globe_page.evaluate("!state.globe.trackedEntity && state.cameraMode === 'manual'")
    assert (
        globe_page.evaluate("Cesium.Cartesian3.clone(state.globe.camera.positionWC)")
        != before_selection
    )
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    globe_page.locator("#camera-follow").click()
    globe_page.wait_for_function(
        "state.globe.trackedEntity?.id === 'satellite-' + state.selectedSatelliteId"
    )
    before = globe_page.evaluate("Cesium.Cartesian3.clone(state.globe.camera.positionWC)")
    globe_page.evaluate("setReplayTime(1800, true)")
    globe_page.wait_for_timeout(300)
    after = globe_page.evaluate("Cesium.Cartesian3.clone(state.globe.camera.positionWC)")
    assert before != after
    globe_page.wait_for_function("""() => {
      const viewer = state.globe, hud = document.getElementById('orbit-hud');
      const point = Cesium.SceneTransforms.worldToWindowCoordinates(viewer.scene,
        state.orbitPositions.get(state.selectedSatelliteId).getValue(viewer.clock.currentTime));
      const map = elements.globe.getBoundingClientRect(), popup = hud.getBoundingClientRect();
      return point && !hud.hidden
        && (popup.left >= map.left+point.x+11 || popup.right <= map.left+point.x-11)
        && popup.top >= map.top && popup.bottom <= map.bottom;
    }""")
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
      return past.show.getValue() && future.show.getValue() && future.leadTime.getValue() > 0;
    })""")
    globe_page.locator("#camera-overview").click()
    assert globe_page.evaluate("!state.globe.trackedEntity")
    assert globe_page.locator("#camera-overview").get_attribute("aria-pressed") == "true"
    globe_page.locator("#toggle-layers").click()
    globe_page.locator("#toggle-track").click()
    globe_page.keyboard.press("Escape")
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


def test_plan_reload_clears_satellite_tracking_and_retains_source_geometry(globe_page: Any) -> None:
    globe_page.locator("#camera-follow").click()
    assert globe_page.evaluate("Boolean(state.globe.trackedEntity)")
    assert globe_page.evaluate("""() => state.currentPayload.replay.orbits
      .filter(orbit => orbit.satellite_id !== state.selectedSatelliteId)
      .every(orbit => state.globe.entities.getById('orbit-preview-' + orbit.satellite_id)
        .path.material === state.orbitStyles.get(orbit.satellite_id).dimmed.future)
    """)
    globe_page.locator("#solver-select").select_option("eos-ppo-profit")
    globe_page.wait_for_function(
        "state.currentPayload.reference_plan.plan_id === 'eos-ppo-profit' && !state.busy"
    )
    assert globe_page.locator("#orbit-hud").is_hidden()
    assert globe_page.evaluate("!state.globe.trackedEntity && state.orbitPositions.size === 20")
    assert globe_page.evaluate(
        "state.globe.entities.values.filter(e=>e.id.startsWith('satellite-')).length === 20"
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
def test_planar_follow_keeps_the_selected_satellite_in_view(
    globe_page: Any, selector: str, mode: str
) -> None:
    globe_page.locator(selector).click()
    globe_page.wait_for_function(
        "mode => state.viewMode === mode && !state.viewTransition", arg=mode
    )
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
def test_plan_reload_retains_planar_view_and_source_orbits(
    globe_page: Any, selector: str, mode: str
) -> None:
    globe_page.locator(selector).click()
    globe_page.wait_for_function(
        "mode => state.viewMode === mode && !state.viewTransition", arg=mode
    )
    globe_page.locator("#solver-select").select_option("eos-sa-profit")
    globe_page.wait_for_function(
        "state.currentPayload.reference_plan.plan_id === 'eos-sa-profit' && !state.busy"
    )
    assert globe_page.evaluate("state.viewMode") == mode
    assert globe_page.locator(selector).get_attribute("aria-pressed") == "true"
    assert globe_page.evaluate("!state.globe.trackedEntity && state.orbitPositions.size === 20")
    assert globe_page.evaluate(
        "state.globe.entities.values.filter(e=>e.id.startsWith('satellite-')).length === 20"
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
    before = globe_page.evaluate("Cesium.Cartesian3.clone(state.globe.camera.positionWC)")
    globe_page.mouse.dblclick(candidate["x"], candidate["y"])
    globe_page.wait_for_function("state.cameraMode === 'manual' && !state.globe.trackedEntity")
    globe_page.wait_for_timeout(750)
    assert globe_page.locator("#camera-focus").count() == 0
    assert globe_page.evaluate("Cesium.Cartesian3.clone(state.globe.camera.positionWC)") != before
    assert_single_screen(globe_page)


def test_loading_another_plan_during_a_view_transition_keeps_the_scene_healthy(
    globe_page: Any,
) -> None:
    globe_page.evaluate("setMapViewMode('2d')")
    globe_page.locator("#solver-select").select_option("eos-ppo-profit")
    globe_page.wait_for_function(
        "state.currentPayload.reference_plan.plan_id === 'eos-ppo-profit' && !state.busy "
        "&& !state.viewTransition"
    )
    assert globe_page.evaluate("state.viewMode") == "2d"
    assert globe_page.evaluate("state.currentPayload.result.metrics.completed_tasks") == 492
    assert globe_page.evaluate("state.orbitPositions.size") == 20
    assert_single_screen(globe_page)
