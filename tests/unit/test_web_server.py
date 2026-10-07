from io import BytesIO
from pathlib import Path
from typing import Any

import orbitops.web.server as server_module
import pytest
from orbitops.web import LabApplication, WebResponse
from orbitops.web.server import LabRequestHandler

PROJECT_ROOT = Path(__file__).parents[2]
REFERENCE_PATH = PROJECT_ROOT / "data/eos-bench/reference.json"


def bare_handler(application: LabApplication) -> Any:
    handler = object.__new__(LabRequestHandler)
    handler.application = application
    return handler


def test_handler_writes_security_headers_and_body() -> None:
    handler = bare_handler(LabApplication(REFERENCE_PATH))
    statuses: list[int] = []
    headers: dict[str, str] = {}
    handler.send_response = statuses.append
    handler.send_header = headers.__setitem__
    handler.end_headers = lambda: None
    handler.wfile = BytesIO()
    response = WebResponse.json(200, {"status": "ok"})

    handler._send(response)

    assert statuses == [200]
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert headers["Content-Length"] == str(len(response.body))
    assert headers["Cache-Control"] == "no-store"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    assert (
        "script-src 'self' 'unsafe-eval' https://cesium.com" in headers["Content-Security-Policy"]
    )
    assert "https://gibs.earthdata.nasa.gov" in headers["Content-Security-Policy"]
    assert handler.wfile.getvalue() == response.body


def test_handler_dispatches_get_and_refuses_post() -> None:
    handler = bare_handler(LabApplication(REFERENCE_PATH))
    responses: list[WebResponse] = []
    handler._send = responses.append
    handler.path = "/api/health"

    handler.do_GET()

    handler.path = "/api/solve"
    body = b'{"scenario_id":"demo-001","solver_name":"greedy-insertion"}'
    handler.headers = {"Content-Length": str(len(body))}
    handler.rfile = BytesIO(body)
    handler.do_POST()

    assert [response.status for response in responses] == [200, 405]
    assert handler.rfile.tell() == 0


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_handler_refuses_writes_without_reading_any_body(method: str) -> None:
    handler = bare_handler(LabApplication(REFERENCE_PATH))
    responses: list[WebResponse] = []
    handler._send = responses.append
    handler.path = "/api/solve"

    class UnreadableBody:
        def read(self, *args: object) -> bytes:
            raise AssertionError("Read-only service must not buffer request bodies")

    handler.rfile = UnreadableBody()

    for content_length in ("invalid", "-1", str(10**12)):
        handler.headers = {"Content-Length": content_length}
        getattr(handler, f"do_{method}")()

    assert [response.status for response in responses] == [405, 405, 405]


def test_method_not_allowed_advertises_only_get() -> None:
    handler = bare_handler(LabApplication(REFERENCE_PATH))
    headers: dict[str, str] = {}
    handler.send_response = lambda status: None
    handler.send_header = headers.__setitem__
    handler.end_headers = lambda: None
    handler.wfile = BytesIO()
    handler._send(handler.application.dispatch("POST", "/api/solve"))
    assert headers["Allow"] == "GET"


def test_make_server_configures_application(monkeypatch: Any) -> None:
    captured: dict[str, object] = {}

    def fake_server(address: tuple[str, int], handler: type[LabRequestHandler]) -> object:
        captured.update(address=address, handler=handler)
        return object()

    monkeypatch.setattr(server_module, "ThreadingHTTPServer", fake_server)

    result = server_module.make_server(REFERENCE_PATH, host="127.0.0.2", port=8123)

    assert result is not None
    assert captured["address"] == ("127.0.0.2", 8123)
    configured_handler = captured["handler"]
    assert configured_handler.application.dispatch("GET", "/api/health").status == 200  # type: ignore[union-attr]


def test_serve_lab_always_closes_server(monkeypatch: Any) -> None:
    events: list[str] = []

    class FakeServer:
        def serve_forever(self) -> None:
            events.append("serve")

        def server_close(self) -> None:
            events.append("close")

    monkeypatch.setattr(server_module, "make_server", lambda *args, **kwargs: FakeServer())

    server_module.serve_lab(REFERENCE_PATH)

    assert events == ["serve", "close"]
