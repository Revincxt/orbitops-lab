"""Threaded local HTTP server for OrbitOps Web Lab."""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

from orbitops.web.app import MAX_REQUEST_BYTES, LabApplication, WebResponse


class LabRequestHandler(BaseHTTPRequestHandler):
    application: ClassVar[LabApplication]
    server_version = "OrbitOpsLab/0.1"

    def _send(self, response: WebResponse) -> None:
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(response.body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
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
        raw_length = self.headers.get("Content-Length", "0")
        try:
            content_length = int(raw_length)
        except ValueError:
            response = WebResponse.json(HTTPStatus.BAD_REQUEST, {"error": "invalid content length"})
            self._send(response)
            return
        if content_length < 0:
            response = WebResponse.json(HTTPStatus.BAD_REQUEST, {"error": "invalid content length"})
            self._send(response)
            return
        if content_length > MAX_REQUEST_BYTES:
            self._send(
                WebResponse.json(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    {"error": "request body exceeds 64 KiB"},
                )
            )
            return
        body = self.rfile.read(content_length)
        self._send(self.application.dispatch("POST", self.path, body))


def make_server(
    scenario_dir: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> ThreadingHTTPServer:
    application = LabApplication(scenario_dir)
    handler = type(
        "ConfiguredLabRequestHandler",
        (LabRequestHandler,),
        {"application": application},
    )
    return ThreadingHTTPServer((host, port), handler)


def serve_lab(
    scenario_dir: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    server = make_server(scenario_dir, host=host, port=port)
    try:
        server.serve_forever()
    finally:
        server.server_close()
