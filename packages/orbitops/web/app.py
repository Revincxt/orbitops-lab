"""Read-only application layer for the EOS-Bench replay workspace."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from orbitops.web.reference import ReferenceArchive

STATIC_DIR = Path(__file__).with_name("static")
DEFAULT_REFERENCE_PATH = Path("data/eos-bench/reference.json")


@dataclass(frozen=True, slots=True)
class WebResponse:
    status: int
    content_type: str
    body: bytes

    @classmethod
    def json(cls, status: int, payload: Any) -> WebResponse:
        return cls(
            status=status,
            content_type="application/json; charset=utf-8",
            body=(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode(),
        )


class LabApplication:
    """Serve a pinned reference archive and a fixed set of browser assets."""

    def __init__(
        self,
        reference_path: str | Path = DEFAULT_REFERENCE_PATH,
        static_dir: str | Path = STATIC_DIR,
    ) -> None:
        self.static_dir = Path(static_dir)
        self.reference = ReferenceArchive(Path(reference_path))

    def _static(self, filename: str, content_type: str) -> WebResponse:
        path = self.static_dir / filename
        try:
            body = path.read_bytes()
        except OSError:
            return WebResponse.json(404, {"error": "static asset not found"})
        return WebResponse(status=200, content_type=content_type, body=body)

    def dispatch(self, method: str, path: str) -> WebResponse:
        if method != "GET":
            return WebResponse.json(405, {"error": "read-only replay service; use GET"})
        route = path.split("?", 1)[0]
        if route == "/api/health":
            available = self.reference.data is not None
            return WebResponse.json(
                200 if available else 503,
                {
                    "status": "ok" if available else "unavailable",
                    "mode": "eos-bench-reference-replay",
                    "scenario_count": 1 if available else 0,
                },
            )
        if route == "/api/reference/data":
            data = self.reference.export()
            if data is None:
                return WebResponse.json(503, {"error": "EOS-Bench reference data is unavailable"})
            return WebResponse.json(200, data)
        if route.startswith("/orbit-data/"):
            try:
                raw = self.reference.orbit_chunk(route.removeprefix("/orbit-data/"))
                return WebResponse(
                    status=200, content_type="application/json; charset=utf-8", body=raw
                )
            except (ValueError, OSError):
                return WebResponse.json(404, {"error": "orbit chunk unavailable"})
        static_routes = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/app.css": ("app.css", "text/css; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/replay.js": ("replay.js", "text/javascript; charset=utf-8"),
            "/orbit-model.js": ("orbit-model.js", "text/javascript; charset=utf-8"),
            "/orbit-ephemeris.js": ("orbit-ephemeris.js", "text/javascript; charset=utf-8"),
            "/satellite-attitude.js": ("satellite-attitude.js", "text/javascript; charset=utf-8"),
            "/sensor-fov.js": ("sensor-fov.js", "text/javascript; charset=utf-8"),
            "/mission.js": ("mission.js", "text/javascript; charset=utf-8"),
            "/models/earth-observer.glb": ("models/earth-observer.glb", "model/gltf-binary"),
            "/favicon.svg": ("favicon.svg", "image/svg+xml"),
            "/cesium-config.js": ("cesium-config.js", "text/javascript; charset=utf-8"),
            "/deployment-config.js": ("deployment-config.js", "text/javascript; charset=utf-8"),
            "/fonts/InterVariable.woff2": ("fonts/InterVariable.woff2", "font/woff2"),
            "/fonts/OFL.txt": ("fonts/OFL.txt", "text/plain; charset=utf-8"),
        }
        if route in static_routes:
            return self._static(*static_routes[route])
        return WebResponse.json(404, {"error": "route not found"})
