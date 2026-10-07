"""Threaded local HTTP server for OrbitOps Web Lab."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

from orbitops.web.app import DEFAULT_REFERENCE_PATH, LabApplication, WebResponse


class LabRequestHandler(BaseHTTPRequestHandler):
    application: ClassVar[LabApplication]
    server_version = "OrbitOpsLab"

    def _send(self, response: WebResponse) -> None:
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(response.body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if response.status == 405:
            self.send_header("Allow", "GET")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-eval' https://cesium.com; "
            "style-src 'self' https://cesium.com; img-src 'self' data: blob: https://cesium.com "
            "https://gibs.earthdata.nasa.gov; "
            "font-src 'self' data: https://cesium.com; worker-src 'self' blob: https://cesium.com; "
            "connect-src 'self' https://cesium.com https://gibs.earthdata.nasa.gov; "
            "object-src 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(response.body)

    def do_GET(self) -> None:
        self._send(self.application.dispatch("GET", self.path))

    def do_POST(self) -> None:
        # Refuse writes without parsing or buffering untrusted request bodies.
        self._send(self.application.dispatch("POST", self.path))

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST


def make_server(
    reference_path: str | Path = DEFAULT_REFERENCE_PATH,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> ThreadingHTTPServer:
    application = LabApplication(reference_path)
    handler = type(
        "ConfiguredLabRequestHandler",
        (LabRequestHandler,),
        {"application": application},
    )
    return ThreadingHTTPServer((host, port), handler)


def serve_lab(
    reference_path: str | Path = DEFAULT_REFERENCE_PATH,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    server = make_server(reference_path, host=host, port=port)
    try:
        server.serve_forever()
    finally:
        server.server_close()
