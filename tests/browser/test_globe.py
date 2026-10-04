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
        assert orbit["future"] == pytest.approx(orbit["period"] / 2)
        assert orbit["futureShown"] and orbit["pastShown"]
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


def test_all_twenty_cone_tips_track_native_satellites_with_a_full_15_degree_fov(
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
            assert cone["angle"] == pytest.approx(15, abs=1e-10), cone
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


def test_satellite_canvas_picking_double_click_focus_follow_and_source_horizon(
    globe_page: Any,
) -> None:
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
    globe_page.locator("#run-button").click()
    globe_page.wait_for_function(
        "state.currentPayload.reference_plan.plan_id === 'eos-ppo-profit' && !state.busy"
    )
    assert globe_page.locator("#orbit-hud").is_visible()
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
    globe_page.locator("#run-button").click()
    globe_page.wait_for_function(
        "state.currentPayload.reference_plan.plan_id === 'eos-sa-profit' && !state.busy"
    )
    assert globe_page.evaluate("state.viewMode") == mode
    assert globe_page.locator(selector).get_attribute("aria-pressed") == "true"
    assert globe_page.evaluate("!state.globe.trackedEntity && state.orbitPositions.size === 20")
    assert globe_page.evaluate(
        "state.globe.entities.values.filter(e=>e.id.startsWith('satellite-')).length === 20"
    )
    assert globe_page.locator("#orbit-hud").is_visible()
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
    globe_page.locator("#run-button").click()
    globe_page.wait_for_function(
        "state.currentPayload.reference_plan.plan_id === 'eos-ppo-profit' && !state.busy "
        "&& !state.viewTransition"
    )
    assert globe_page.evaluate("state.viewMode") == "2d"
    assert globe_page.evaluate("state.currentPayload.result.metrics.completed_tasks") == 492
    assert globe_page.evaluate("state.orbitPositions.size") == 20
    assert_single_screen(globe_page)
