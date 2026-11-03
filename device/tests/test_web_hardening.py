"""Device web server: what a LAN client can no longer do to a demo unit.

A request that promises a body it never sends used to pin a handler thread
forever; a huge or negative Content-Length was read straight into RAM (or
until the client hung up) on a 128 MB board; and with CORS wide open any web
page on a phone on the same WiFi could read /snapshot.
"""

import socket
import threading
import time
import types
from functools import partial
from http.server import ThreadingHTTPServer

import pytest

from config import cfg, migrate_cors


@pytest.fixture
def server(monkeypatch):
    from server.web_server import IsoraHandler

    class _NullLogger:
        def __getattr__(self, _name):
            return lambda *a, **k: None

    monkeypatch.setattr(cfg, "_data", dict(cfg._data))
    monkeypatch.setattr(cfg, "update", lambda m: cfg._data.update(m))
    monkeypatch.setattr(IsoraHandler, "timeout", 1)
    orch = types.SimpleNamespace(commands=[], presses=[],
                                 simulate_button=lambda w, l: True)
    srv = ThreadingHTTPServer(("127.0.0.1", 0),
                              partial(IsoraHandler, orch, _NullLogger(), None))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_port
    srv.shutdown()
    srv.server_close()


def _raw(port, data: bytes, read_timeout=5.0) -> bytes:
    s = socket.create_connection(("127.0.0.1", port), timeout=read_timeout)
    try:
        s.sendall(data)
        out = b""
        while True:
            try:
                chunk = s.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            out += chunk
        return out
    finally:
        s.close()


def _post(path, length, body=b""):
    return (b"POST %s HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
            b"Content-Length: %s\r\n\r\n" % (path.encode(), str(length).encode())) + body


def test_a_huge_body_is_refused_before_it_is_read(server):
    out = _raw(server, _post("/button", 50 * 1024 * 1024))
    assert out.startswith(b"HTTP/1.0 413") or out.startswith(b"HTTP/1.1 413")


@pytest.mark.parametrize("length", ["-1", "abc"])
def test_a_length_that_is_not_a_length_is_refused(server, length):
    out = _raw(server, _post("/button", length))
    assert b" 400 " in out.split(b"\r\n")[0]


def test_a_promised_body_that_never_comes_frees_the_thread(server):
    # Claims 100 bytes, sends 2. Must time out instead of waiting forever.
    t = time.monotonic()
    _raw(server, _post("/button", 100, b"{}"), read_timeout=10)
    assert time.monotonic() - t < 5


def test_a_normal_post_still_works(server):
    body = b'{"button": "action"}'
    out = _raw(server, _post("/button", len(body), body))
    assert b" 200 " in out.split(b"\r\n")[0]


def test_cross_origin_pages_cannot_read_the_device(server):
    out = _raw(server, b"GET /status HTTP/1.1\r\nHost: x\r\n"
                       b"Origin: http://evil.example\r\n\r\n")
    headers = out.split(b"\r\n\r\n", 1)[0].lower()
    assert b"access-control-allow-origin: *" not in headers
    assert b"access-control-allow-origin: http://evil.example" not in headers


def test_a_sandboxed_iframe_gets_no_grant_either(server):
    # A sandboxed iframe sends Origin: null; "ACAO: null" would let it read.
    out = _raw(server, b"GET /status HTTP/1.1\r\nHost: x\r\nOrigin: null\r\n\r\n")
    headers = out.split(b"\r\n\r\n", 1)[0].lower()
    assert b"access-control-allow-origin" not in headers


def test_old_wide_open_cors_default_is_migrated():
    assert migrate_cors({"cors_allowed_origins": ["*"]}) == {"cors_allowed_origins": []}
    # An operator's own list is theirs.
    assert migrate_cors({"cors_allowed_origins": ["http://lab.local"]}) == {}
    assert migrate_cors({}) == {}
