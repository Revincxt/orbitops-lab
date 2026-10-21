from __future__ import annotations

import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from email.message import Message
from io import BytesIO
from pathlib import Path
from threading import Event
from typing import Any
from urllib.error import HTTPError
from urllib.request import HTTPSHandler, ProxyHandler

import pytest
from orbitops.web import LabApplication
from orbitops.web import imagery as module
from orbitops.web.imagery import CACHE_TTL, MAX_TILE_BYTES, NasaTileCache, TileUnavailable

JPEG = b"\xff\xd8sample\xff\xd9"
REFERENCE = Path(__file__).parents[2] / "data/eos-bench/reference.json"


@pytest.mark.parametrize(
    "route",
    [
        "/imagery/nasa/9/0/0.jpeg",
        "/imagery/nasa/0/0/1.jpeg",
        "/imagery/nasa/1/2/0.jpeg",
        "/imagery/nasa/8/0/256.jpeg",
        "/imagery/nasa/1/-1/0.jpeg",
        "/imagery/nasa/01/0/0.jpeg",
        "/imagery/nasa/1/00/0.jpeg",
        "/imagery/nasa/1/0/0.jpeg/extra",
        "/imagery/nasa/1/0/0.png",
        "/imagery/nasa/../secret",
        "/imagery/nasa/%2e%2e/secret",
        "/imagery/nasa/https://example.com/image.jpeg",
        "/imagery/nasa/1/0/\u0660.jpeg",
    ],
)
def test_only_fixed_valid_tile_coordinates_are_allowed(tmp_path: Path, route: str) -> None:
    def forbidden(coordinates: str) -> bytes:
        raise AssertionError("Invalid coordinates must never access the network")

    cache = NasaTileCache(tmp_path / "cache", fetcher=forbidden)
    with pytest.raises(TileUnavailable) as error:
        cache.get(route)
    assert error.value.status == 404
    assert not cache.cache_dir.exists()


def test_hits_are_shared_in_memory_and_across_cache_instances(tmp_path: Path) -> None:
    requests = []

    def fetch(coordinates: str) -> bytes:
        requests.append(coordinates)
        return JPEG

    cache = NasaTileCache(tmp_path, fetcher=fetch)
    assert cache.get("/imagery/nasa/1/0/1.jpeg") == JPEG
    assert cache.get("/imagery/nasa/1/0/1.jpeg") is cache.get("/imagery/nasa/1/0/1.jpeg")
    restarted = NasaTileCache(tmp_path, fetcher=fetch)
    assert restarted.get("/imagery/nasa/1/0/1.jpeg") == JPEG
    assert requests == ["1/0/1.jpeg"]
    assert (tmp_path / "1-0-1.jpeg").read_bytes() == JPEG


def test_concurrent_misses_fetch_the_same_tile_only_once(tmp_path: Path) -> None:
    started, release = Event(), Event()
    requests = []

    def fetch(coordinates: str) -> bytes:
        requests.append(coordinates)
        started.set()
        assert release.wait(5)
        return JPEG

    cache = NasaTileCache(tmp_path, fetcher=fetch)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(cache.get, "/imagery/nasa/1/0/1.jpeg") for _ in range(16)]
        assert started.wait(5)
        release.set()
        assert all(future.result() == JPEG for future in futures)
    assert requests == ["1/0/1.jpeg"]
    assert not cache._pending


def test_download_concurrency_and_pending_work_are_bounded(tmp_path: Path) -> None:
    release, first, second = Event(), Event(), Event()

    def fetch(coordinates: str) -> bytes:
        (first if coordinates.endswith("0.jpeg") else second).set()
        assert release.wait(5)
        return JPEG

    cache = NasaTileCache(tmp_path, fetcher=fetch, max_concurrent=2, max_pending=2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(cache.get, f"/imagery/nasa/2/0/{x}.jpeg") for x in (0, 1)]
        try:
            assert first.wait(5) and second.wait(5)
            with pytest.raises(TileUnavailable) as error:
                cache.get("/imagery/nasa/2/0/2.jpeg")
            assert error.value.status == 503
            assert len(cache._pending) == 2
        finally:
            release.set()
        assert all(job.result() == JPEG for job in jobs)


def test_small_bursts_queue_without_exceeding_the_download_limit(tmp_path: Path) -> None:
    started, release = Event(), Event()
    calls = []

    def fetch(coordinates: str) -> bytes:
        calls.append(coordinates)
        started.set()
        assert release.wait(5)
        return JPEG

    cache = NasaTileCache(tmp_path, fetcher=fetch, max_concurrent=1, max_pending=4)
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = [pool.submit(cache.get, f"/imagery/nasa/2/0/{x}.jpeg") for x in range(4)]
        assert started.wait(5)
        assert len(calls) == 1
        release.set()
        assert all(job.result() == JPEG for job in jobs)
    assert len(calls) == 4


def test_memory_and_disk_byte_limits_are_enforced(tmp_path: Path) -> None:
    cache = NasaTileCache(
        tmp_path, fetcher=lambda _: JPEG, max_memory_bytes=len(JPEG), max_disk_bytes=2 * len(JPEG)
    )
    for x in range(4):
        assert cache.get(f"/imagery/nasa/2/0/{x}.jpeg") == JPEG
    assert cache._memory_bytes <= len(JPEG)
    assert sum(path.stat().st_size for path in tmp_path.glob("*.jpeg")) <= 2 * len(JPEG)
    assert len(list(tmp_path.glob("*.jpeg"))) == 2


def test_disk_ttl_invalid_images_and_symlinks_do_not_become_hits(tmp_path: Path) -> None:
    requests = []
    clock = [time.time() + 1]
    cache = NasaTileCache(
        tmp_path, fetcher=lambda key: requests.append(key) or JPEG, clock=lambda: clock[0]
    )
    route = "/imagery/nasa/1/0/1.jpeg"
    cache.get(route)
    clock[0] += CACHE_TTL + 1
    assert cache.get(route) == JPEG
    assert len(requests) == 2
    (tmp_path / "1-0-0.jpeg").write_bytes(b"not an image")
    assert cache.get("/imagery/nasa/1/0/0.jpeg") == JPEG
    external = tmp_path / "unrelated.txt"
    external.write_bytes(b"keep this")
    (tmp_path / "1-1-0.jpeg").symlink_to(external)
    assert cache.get("/imagery/nasa/1/1/0.jpeg") == JPEG
    assert external.read_bytes() == b"keep this"


def test_readonly_cache_does_not_break_successful_downloads(tmp_path: Path) -> None:
    path = tmp_path / "not-a-directory"
    path.write_bytes(b"preserve")
    cache = NasaTileCache(path, fetcher=lambda _: JPEG)
    assert cache.get("/imagery/nasa/0/0/0.jpeg") == JPEG
    assert path.read_bytes() == b"preserve"


def test_symlinked_cache_parents_are_not_written(tmp_path: Path) -> None:
    target = tmp_path / "unrelated"
    target.mkdir()
    alias = tmp_path / "linked"
    alias.symlink_to(target, target_is_directory=True)
    cache = NasaTileCache(alias / "cache", fetcher=lambda _: JPEG)
    assert cache.get("/imagery/nasa/0/0/0.jpeg") == JPEG
    assert not list(target.iterdir())


def test_tiny_tiles_cannot_grow_memory_cache_metadata_without_bound(tmp_path: Path) -> None:
    cache = NasaTileCache(tmp_path, fetcher=lambda _: b"\xff\xd8\xff\xd9", max_disk_bytes=0)
    for i in range(520):
        cache.get(f"/imagery/nasa/8/{i // 256}/{i % 256}.jpeg")
    assert len(cache._memory) == 512
    assert not list(tmp_path.iterdir())


def test_negative_cache_and_endpoint_cooldown_bound_failed_requests(tmp_path: Path) -> None:
    clock = [time.time()]
    calls = []

    def unavailable(key: str) -> bytes:
        calls.append(key)
        raise OSError("upstream TLS failed")

    cache = NasaTileCache(tmp_path, fetcher=unavailable, clock=lambda: clock[0])
    for _ in range(5):
        with pytest.raises(TileUnavailable):
            cache.get("/imagery/nasa/2/0/0.jpeg")
    assert len(calls) == 1
    for x in (1, 2):
        with pytest.raises(TileUnavailable):
            cache.get(f"/imagery/nasa/2/0/{x}.jpeg")
    with pytest.raises(TileUnavailable):
        cache.get("/imagery/nasa/2/0/3.jpeg")
    assert len(calls) == 3
    assert not list(tmp_path.glob("*.jpeg"))
    clock[0] += 16
    cache._fetcher = lambda _: JPEG
    assert cache.get("/imagery/nasa/2/0/3.jpeg") == JPEG
    assert cache._blocked_until == 0


def test_bad_upstream_payloads_are_never_cached(tmp_path: Path) -> None:
    for index, body in enumerate(
        (b"<html>error</html>", b"\xff\xd8truncated", b"x" * (MAX_TILE_BYTES + 1))
    ):
        cache = NasaTileCache(tmp_path / str(index), fetcher=lambda _, body=body: body)
        with pytest.raises(TileUnavailable) as error:
            cache.get("/imagery/nasa/0/0/0.jpeg")
        assert error.value.status == 502
        assert not cache._memory
        assert not cache.cache_dir.exists()


def test_direct_fetch_keeps_tls_verification_and_disables_proxies_and_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class Response(BytesIO):
        headers = Message()
        headers["Content-Type"] = "image/jpeg"

    class Opener:
        def open(self, request: Any, *, timeout: int) -> Response:
            captured.update(url=request.full_url, timeout=timeout)
            return Response(JPEG)

    def build(*handlers: object) -> Opener:
        captured["handlers"] = handlers
        return Opener()

    monkeypatch.setattr(module, "build_opener", build)
    assert module.fetch_nasa_tile("1/0/1.jpeg") == JPEG
    assert captured["url"] == module.NASA_URL + "1/0/1.jpeg"
    assert captured["timeout"] == 8
    proxy, https, redirect = captured["handlers"]
    assert isinstance(proxy, ProxyHandler) and proxy.proxies == {}
    assert isinstance(https, HTTPSHandler)
    assert https._context.verify_mode == ssl.CERT_REQUIRED
    assert https._context.check_hostname
    assert isinstance(redirect, module._NoRedirect)
    assert (
        redirect.redirect_request(None, None, 302, "redirect", Message(), "http://localhost")
        is None
    )


@pytest.mark.parametrize("status", [302, 404, 429, 500])
def test_upstream_http_errors_are_not_followed_or_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    class Opener:
        def open(self, request: Any, *, timeout: int) -> None:
            raise HTTPError(request.full_url, status, "failed", Message(), None)

    monkeypatch.setattr(module, "build_opener", lambda *args: Opener())
    cache = NasaTileCache(tmp_path)
    with pytest.raises(TileUnavailable) as error:
        cache.get("/imagery/nasa/0/0/0.jpeg")
    assert error.value.status == (404 if status == 404 else 502)
    assert not cache._memory


def test_http_application_serves_only_fixed_tiles_with_browser_cache_headers(
    tmp_path: Path,
) -> None:
    app = LabApplication(REFERENCE)
    app.imagery = NasaTileCache(tmp_path, fetcher=lambda _: JPEG)
    response = app.dispatch("GET", "/imagery/nasa/1/0/1.jpeg?v=1")
    assert response.status == 200
    assert response.body == JPEG
    assert response.content_type == "image/jpeg"
    assert response.cache_control == "public, max-age=86400"
    assert app.dispatch("GET", "/imagery/nasa/9/0/0.jpeg").status == 404
    assert app.dispatch("POST", "/imagery/nasa/1/0/1.jpeg").status == 405
    assert app.dispatch("GET", "/imagery.js").status == 200
