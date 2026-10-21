"""Bounded, direct-access cache for one public NASA Blue Marble tile set.

This is not an arbitrary URL proxy. Coordinates are validated before any network
or filesystem access; redirects and system proxies are deliberately disabled.
"""

from __future__ import annotations

import math
import re
import ssl
import tempfile
import time
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future, TimeoutError
from email.message import Message
from pathlib import Path
from threading import BoundedSemaphore, Lock
from typing import IO
from urllib.error import HTTPError
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)

NASA_URL = (
    "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/"
    "BlueMarble_ShadedRelief/default/GoogleMapsCompatible_Level8/"
)
TILE_ROUTE = re.compile(r"/imagery/nasa/([0-8])/(0|[1-9][0-9]{0,2})/(0|[1-9][0-9]{0,2})\.jpeg\Z")
CACHE_FILE = re.compile(r"[0-8]-(0|[1-9][0-9]{0,2})-(0|[1-9][0-9]{0,2})\.jpeg\Z")
MAX_TILE_BYTES = 1024 * 1024
NETWORK_TIMEOUT = 8
CACHE_TTL = 7 * 86400


class TileUnavailable(Exception):
    def __init__(self, status: int = 503, retry_after: int = 3) -> None:
        super().__init__("NASA imagery is temporarily unavailable")
        self.status = status
        self.retry_after = retry_after


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Request, fp: IO[bytes], code: int, msg: str, headers: Message, newurl: str
    ) -> None:
        return None


def _valid_image(body: bytes) -> bool:
    return (
        4 <= len(body) <= MAX_TILE_BYTES
        and body.startswith(b"\xff\xd8")
        and body.endswith(b"\xff\xd9")
    )


def fetch_nasa_tile(coordinates: str) -> bytes:
    context = ssl.create_default_context()
    # Some macOS Python installations do not have their own CA bundle installed.
    # Use the system bundle when present; certificate verification stays enabled.
    if not context.cert_store_stats()["x509_ca"] and Path("/etc/ssl/cert.pem").is_file():
        context.load_verify_locations(cafile="/etc/ssl/cert.pem")
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context), _NoRedirect())
    request = Request(NASA_URL + coordinates, headers={"User-Agent": "OrbitOps-Lab/0.2"})
    try:
        with opener.open(request, timeout=NETWORK_TIMEOUT) as response:
            if response.headers.get_content_type() != "image/jpeg":
                raise TileUnavailable(502)
            body: bytes = response.read(MAX_TILE_BYTES + 1)
    except HTTPError as error:
        raise TileUnavailable(404 if error.code == 404 else 502) from None
    if not _valid_image(body):
        raise TileUnavailable(502)
    return body


class NasaTileCache:
    """Deduplicate misses, bound downloads and cache only requested JPEG tiles."""

    def __init__(
        self,
        cache_dir: Path = Path("runs/cache/nasa-blue-marble-v1"),
        *,
        max_disk_bytes: int = 100 * 1024 * 1024,
        max_memory_bytes: int = 8 * 1024 * 1024,
        max_concurrent: int = 4,
        max_pending: int = 32,
        fetcher: Callable[[str], bytes] = fetch_nasa_tile,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if (
            min(max_disk_bytes, max_memory_bytes) < 0
            or max_concurrent < 1
            or max_pending < max_concurrent
        ):
            raise ValueError("invalid imagery cache limits")
        self.cache_dir = cache_dir
        self.max_disk_bytes = max_disk_bytes
        self.max_memory_bytes = max_memory_bytes
        self.max_concurrent = max_concurrent
        self.max_pending = max_pending
        self._slots = BoundedSemaphore(max_concurrent)
        self._fetcher = fetcher
        self._clock = clock
        self._lock = Lock()
        self._memory: OrderedDict[str, tuple[float, bytes]] = OrderedDict()
        self._memory_bytes = 0
        self._pending: dict[str, Future[tuple[int, bytes]]] = {}
        self._failures: OrderedDict[str, tuple[float, int]] = OrderedDict()
        self._consecutive_failures = 0
        self._blocked_until = 0.0

    def get(self, route: str) -> bytes:
        match = TILE_ROUTE.fullmatch(route)
        if not match:
            raise TileUnavailable(404)
        z, y, x = map(int, match.groups())
        if x >= 2**z or y >= 2**z:
            raise TileUnavailable(404)
        key = f"{z}-{y}-{x}.jpeg"
        now = self._clock()
        with self._lock:
            cached = self._read(key, now)
            if cached is not None:
                return cached
            future = self._pending.get(key)
            owner = future is None
            if owner:
                failed_until, status = self._failures.get(key, (0.0, 503))
                if now < failed_until or now < self._blocked_until:
                    delay = max(failed_until, self._blocked_until) - now
                    raise TileUnavailable(status, max(1, math.ceil(delay)))
                if len(self._pending) >= self.max_pending:
                    raise TileUnavailable(503, 1)
                future = Future()
                self._pending[key] = future
        assert future is not None
        if not owner:
            try:
                status, body = future.result(timeout=NETWORK_TIMEOUT * 2 + 1)
            except TimeoutError:
                raise TileUnavailable() from None
            if status != 200:
                raise TileUnavailable(status)
            return body

        try:
            if not self._slots.acquire(timeout=NETWORK_TIMEOUT):
                raise TileUnavailable()
            try:
                with self._lock:
                    if self._clock() < self._blocked_until:
                        raise TileUnavailable()
                body = self._fetcher(f"{z}/{y}/{x}.jpeg")
                if not _valid_image(body):
                    raise TileUnavailable(502)
            finally:
                self._slots.release()
            status = 200
        except Exception as error:
            body = b""
            status = error.status if isinstance(error, TileUnavailable) else 502
        with self._lock:
            if status == 200:
                self._consecutive_failures = 0
                self._blocked_until = 0
                self._failures.pop(key, None)
                self._remember(key, now + CACHE_TTL, body)
                self._write(key, body)
            else:
                self._failures[key] = (self._clock() + 3, status)
                self._failures.move_to_end(key)
                while len(self._failures) > 128:
                    self._failures.popitem(last=False)
                if status not in (404, 503):
                    self._consecutive_failures += 1
                    if self._consecutive_failures >= 3:
                        self._blocked_until = self._clock() + 15
            self._pending.pop(key)
            future.set_result((status, body))
        if status != 200:
            raise TileUnavailable(status)
        return body

    def _remember(self, key: str, expires: float, body: bytes) -> None:
        previous = self._memory.pop(key, None)
        if previous:
            self._memory_bytes -= len(previous[1])
        if len(body) <= self.max_memory_bytes:
            self._memory[key] = (expires, body)
            self._memory_bytes += len(body)
        while self._memory_bytes > self.max_memory_bytes or len(self._memory) > 512:
            _, (_, removed) = self._memory.popitem(last=False)
            self._memory_bytes -= len(removed)

    def _read(self, key: str, now: float) -> bytes | None:
        entry = self._memory.get(key)
        if entry:
            if now < entry[0]:
                self._memory.move_to_end(key)
                return entry[1]
            self._memory_bytes -= len(self._memory.pop(key)[1])
        path = self.cache_dir / key
        try:
            if path.is_symlink() or self._cache_path_is_symlinked():
                return None
            stat = path.stat()
            if not 0 <= now - stat.st_mtime < CACHE_TTL or stat.st_size > MAX_TILE_BYTES:
                return None
            body = path.read_bytes()
            if _valid_image(body):
                self._remember(key, stat.st_mtime + CACHE_TTL, body)
                return body
        except OSError:
            pass
        return None

    def _cache_path_is_symlinked(self) -> bool:
        return any(path.is_symlink() for path in (self.cache_dir, *self.cache_dir.parents))

    def _write(self, key: str, body: bytes) -> None:
        if len(body) > self.max_disk_bytes:
            return
        try:
            if self._cache_path_is_symlinked():
                return
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            # Publish complete files atomically, including across server restarts.
            temporary_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(dir=self.cache_dir, delete=False) as temporary:
                    temporary_path = Path(temporary.name)
                    temporary.write(body)
                temporary_path.replace(self.cache_dir / key)
            finally:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)
            files = []
            for path in self.cache_dir.iterdir():
                if CACHE_FILE.fullmatch(path.name) and not path.is_symlink() and path.is_file():
                    stat = path.stat()
                    files.append((stat.st_mtime, path.name, stat.st_size))
            total = sum(size for _, _, size in files)
            count = len(files)
            for _, name, size in sorted(files):
                if total <= self.max_disk_bytes and count <= 2048:
                    break
                (self.cache_dir / name).unlink(missing_ok=True)
                total -= size
                count -= 1
        except OSError:
            # A read-only/full cache directory must not prevent an upstream hit.
            pass
