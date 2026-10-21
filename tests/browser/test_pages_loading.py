"""Exercise the actual Pages artifact, including its browser-owned data cache."""

from __future__ import annotations

import functools
import hashlib
import json
import os
from collections.abc import Iterator
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import pytest
from orbitops.web import LabApplication

from scripts.build_pages import build_pages
from tests.browser.test_globe import cesium_assets as cesium_assets
from tests.browser.test_globe import globe_page as globe_page
from tests.browser.test_workbench import assert_single_screen
from tests.browser.test_workbench import browser as browser

pytestmark = pytest.mark.skipif(
    os.environ.get("ORBITOPS_BROWSER_TESTS") != "1", reason="browser verification is opt-in"
)
ROOT = Path(__file__).parents[2]


@pytest.fixture(scope="module")
def pages_artifact(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("pages-demo") / "orbitops-lab"
    build_pages(output)
    return output


@pytest.fixture(scope="module")
def lab_url(pages_artifact: Path) -> Iterator[str]:
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *_: Any) -> None:
            pass

    handler = functools.partial(QuietHandler, directory=str(pages_artifact.parent))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/orbitops-lab/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


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
        assert not errors
    finally:
        context.unroute_all(behavior="ignoreErrors")
        context.close()


def ready(page: Any, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_function(
        "state.currentPayload && !state.busy && state.ephemeris.pendingCount === 0"
    )
    assert page.evaluate("staticDeployment")


def wait_for_persisted(page: Any, count: int = 1) -> None:
    page.wait_for_function(
        """async count => {
          const cache=await caches.open('orbitops-orbits-v1:/orbitops-lab/');
          return (await cache.keys()).length>=count;
        }""",
        arg=count,
    )


def test_cold_pages_loads_only_one_plan_and_keeps_all_comparison_metrics(
    page: Any, lab_url: str
) -> None:
    requests: list[str] = []
    page.on("request", lambda request: requests.append(request.url))
    ready(page, lab_url)
    plans = [url for url in requests if "/plan-data/" in url]
    assert len(plans) == 1 and "/eos-sa-balanced." in plans[0]
    assert not any("/api/" in url for url in requests)
    assert len([url for url in requests if "/orbit-data/" in url]) == 1
    assert page.evaluate("state.ephemeris.cacheSize") == 1
    assert page.evaluate("state.currentPayload.reference_plan.assignments.length") == 488
    assert page.evaluate("state.referenceData.plans.every(p => !p.assignments && !p.checks)")
    assert page.locator(".radar-series").count() == 7
    assert page.locator("#solver-select option").count() == 7
    assert_single_screen(page)


def test_lazy_switch_waits_without_clearing_the_previous_plan_and_reuses_loaded_plans(
    page: Any, lab_url: str, pages_artifact: Path
) -> None:
    ready(page, lab_url)
    before = page.evaluate("JSON.stringify(state.currentPayload)")
    page.evaluate("window.oldTaskNode=document.querySelector('.target-row')")
    held: list[Any] = []
    page.route("**/plan-data/eos-ppo-profit.*", lambda route: held.append(route))
    page.select_option("#solver-select", "eos-ppo-profit")
    page.wait_for_function("state.busy")
    assert page.evaluate("JSON.stringify(state.currentPayload)") == before
    assert page.evaluate("window.oldTaskNode===document.querySelector('.target-row')")
    assert page.locator(".radar-series").count() == 7
    assert held
    body = (pages_artifact / "plan-data" / held[0].request.url.rsplit("/", 1)[-1]).read_bytes()
    held[0].fulfill(content_type="application/json", body=body)
    page.wait_for_function(
        "!state.busy && state.currentPayload.reference_plan.plan_id==='eos-ppo-profit'"
    )
    assert page.evaluate("state.currentPayload.reference_plan.assignments.length") == 492
    page.unroute("**/plan-data/eos-ppo-profit.*")
    requested: list[str] = []
    page.on("request", lambda request: requested.append(request.url))
    for plan in ["eos-sa-balanced", "eos-ppo-profit"]:
        page.select_option("#solver-select", plan)
        page.wait_for_function(
            "id=>!state.busy && state.currentPayload.reference_plan.plan_id===id", arg=plan
        )
    assert not any("/plan-data/" in url for url in requested)


def test_failed_plan_switch_preserves_selection_and_can_be_retried(page: Any, lab_url: str) -> None:
    ready(page, lab_url)
    page.evaluate("setReplayTime(1200,true)")
    before = page.evaluate("JSON.stringify(state.currentPayload)")
    selection = page.evaluate("[state.selectedTaskId,state.selectedSatelliteId,state.cameraMode]")
    page.route("**/plan-data/eos-mip-profit.*", lambda route: route.fulfill(status=503))
    page.select_option("#solver-select", "eos-mip-profit")
    page.wait_for_function("!state.busy && elements.status.classList.contains('error')")
    assert page.evaluate("JSON.stringify(state.currentPayload)") == before
    assert page.evaluate("state.replay.time") == 1200
    assert (
        page.evaluate("[state.selectedTaskId,state.selectedSatelliteId,state.cameraMode]")
        == selection
    )
    assert page.locator("#solver-select").input_value() == "eos-sa-balanced"
    assert "503" in page.locator("#status").inner_text()
    page.unroute("**/plan-data/eos-mip-profit.*")
    page.select_option("#solver-select", "eos-mip-profit")
    page.wait_for_function(
        "!state.busy && state.currentPayload.reference_plan.plan_id==='eos-mip-profit'"
    )
    assert page.evaluate("state.currentPayload.reference_plan.assignments.length") == 355


def test_reload_reuses_verified_orbits_without_network_requests(page: Any, lab_url: str) -> None:
    ready(page, lab_url)
    wait_for_persisted(page)
    sample = page.evaluate("state.ephemeris.samples('KENT_RIDGE_1_41167',0)")
    requested: list[str] = []
    page.on("request", lambda request: requested.append(request.url))
    ready(page, lab_url)
    assert not any("/orbit-data/" in url for url in requested)
    assert page.evaluate("state.ephemeris.samples('KENT_RIDGE_1_41167',0)") == sample
    assert page.evaluate("state.ephemeris.cacheSize") == 1


def test_reverse_seek_reuses_disk_after_the_four_chunk_memory_cache_evicts_data(
    page: Any, lab_url: str
) -> None:
    ready(page, lab_url)
    for time in range(3600, 43201, 3600):
        page.evaluate("time=>setReplayTime(time,true)", time)
        page.wait_for_function("state.ephemeris.pendingCount===0")
        assert page.evaluate("state.ephemeris.cacheSize") <= 4
    wait_for_persisted(page, 12)
    assert page.evaluate("""async () => {
      const cache=await caches.open('orbitops-orbits-v1:/orbitops-lab/');
      let total=0;
      for(const key of await cache.keys()) {
        total+=Number((await cache.match(key)).headers.get('X-OrbitOps-Bytes'));
      }
      return total<=64*1024*1024;
    }""")
    assert page.evaluate("state.ephemeris.samples('KENT_RIDGE_1_41167',0)") is None
    requested: list[str] = []
    page.on("request", lambda request: requested.append(request.url))
    page.evaluate("setReplayTime(0,true)")
    page.wait_for_function("state.ephemeris.pendingCount===0")
    assert page.evaluate("state.ephemeris.samples('KENT_RIDGE_1_41167',0)")
    assert not any("/orbit-data/" in url for url in requested)


def test_corrupt_disk_cache_is_repaired_from_the_source(page: Any, lab_url: str) -> None:
    ready(page, lab_url)
    wait_for_persisted(page)
    page.evaluate("""async () => {
      const cache=await caches.open('orbitops-orbits-v1:/orbitops-lab/');
      const [key]=await cache.keys();
      await cache.put(key,new Response('corrupt',{headers:{'X-OrbitOps-Bytes':'7'}}));
    }""")
    requested: list[str] = []
    page.on("request", lambda request: requested.append(request.url))
    ready(page, lab_url)
    assert len([url for url in requested if "/orbit-data/" in url]) == 1
    assert page.evaluate("state.ephemeris.samples('KENT_RIDGE_1_41167',0)")


def test_new_orbit_content_version_does_not_reuse_stale_bytes(
    page: Any, lab_url: str, pages_artifact: Path
) -> None:
    ready(page, lab_url)
    wait_for_persisted(page)
    bootstrap = json.loads((pages_artifact / "pages-data.json").read_text())
    entry = bootstrap["reference"]["replay"]["ephemeris"]["chunks"][0]
    # Whitespace changes bytes/hash, but not a single source coordinate value.
    replacement = (pages_artifact / "orbit-data" / entry["filename"]).read_bytes() + b"\n"
    entry.update(bytes=len(replacement), sha256=hashlib.sha256(replacement).hexdigest())
    page.route("**/pages-data.json?*", lambda route: route.fulfill(json=bootstrap))
    page.route("**/orbit-data/00000.json?*", lambda route: route.fulfill(body=replacement))
    requested: list[str] = []
    page.on("request", lambda request: requested.append(request.url))
    ready(page, lab_url)
    transfers = [url for url in requested if "/orbit-data/" in url]
    assert len(transfers) == 1 and entry["sha256"] in transfers[0]
    wait_for_persisted(page, 2)
    requested.clear()
    ready(page, lab_url)
    assert not any("/orbit-data/" in url for url in requested)


def test_storage_denied_falls_back_without_affecting_the_workspace(page: Any, lab_url: str) -> None:
    page.add_init_script(
        "Object.defineProperty(window,'caches',{get(){throw new Error('Storage denied');}})"
    )
    ready(page, lab_url)
    assert page.evaluate("state.currentPayload.reference_plan.assignments.length") == 488
    assert page.evaluate("state.ephemeris.cacheSize") == 1
    assert page.locator(".radar-series").count() == 7
    assert_single_screen(page)


@pytest.mark.skipif(os.environ.get("ORBITOPS_GLOBE_TESTS") != "1", reason="real WebGL is opt-in")
def test_native_pages_keeps_all_plan_values_and_satellite_rendering(globe_page: Any) -> None:
    reference = LabApplication(ROOT / "data/eos-bench/reference.json").reference.export()
    assert globe_page.evaluate("staticDeployment")
    for plan in ["eos-sa-balanced", "eos-ppo-profit", "eos-greedy-profit"]:
        globe_page.select_option("#solver-select", plan)
        globe_page.wait_for_function(
            "id=>!state.busy && state.currentPayload.reference_plan.plan_id===id", arg=plan
        )
        assert globe_page.evaluate(
            """archive => JSON.stringify(state.currentPayload) === JSON.stringify(
              OrbitReplay.referencePayload(archive,archive.plans.find(
                p=>p.plan_id===state.currentPayload.reference_plan.plan_id)))""",
            reference,
        )
        assert globe_page.evaluate("state.orbitPositions.size") == 20
        assert globe_page.evaluate("state.sensorFovs.size") == 20
        assert globe_page.locator(".radar-series").count() == 7
        assert_single_screen(globe_page)
