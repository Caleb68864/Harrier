"""O1c: the Playwright render must not let Chromium resolve or connect itself.

Every request the page makes (main document, cross-host redirect targets,
scripts, XHR) is fetched by Harrier over a connection pinned to the address it
checked, and handed to Chromium with ``route.fulfill``. Chromium's own resolver
is never trusted.

No real network: a fake resolver answers for ``*.example`` hosts, a fake
connector sends every "public" address to a local test server, and Chromium's
resolver is made hostile (every unpinned name points at a local "internal"
server that must never be hit).
"""

from __future__ import annotations

import ipaddress
import os
import shutil
import socket
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from harrier import verify

_REAL_CREATE_CONNECTION = socket.create_connection


# --- unit level: fake Playwright, rebinding resolver ------------------------

class _FakeSock:
    def __init__(self, response: bytes):
        import io
        self._response = response
        self._io = io
        self.sent = b""

    def sendall(self, data):
        self.sent += data

    def makefile(self, *a, **k):
        return self._io.BytesIO(self._response)

    def setsockopt(self, *a, **k):
        pass

    def settimeout(self, *a, **k):
        pass

    def close(self):
        pass


class _Req:
    def __init__(self, url, method="GET", resource_type="document", body=None):
        self.url = url
        self.method = method
        self.resource_type = resource_type
        self._body = body

    def all_headers(self):
        return {"user-agent": "UA", "accept": "*/*", "accept-encoding": "gzip, br",
                "host": "spoofed.example", "connection": "keep-alive"}

    @property
    def headers(self):
        return self.all_headers()

    @property
    def post_data_buffer(self):
        return self._body


class _Route:
    def __init__(self, url, **kw):
        self.request = _Req(url, **kw)
        self.action = None
        self.fulfilled = None

    def continue_(self, **kw):
        self.action = "continue"

    def fallback(self, **kw):
        self.action = "continue"

    def abort(self, error_code=None):
        self.action = "abort"

    def fulfill(self, status=None, headers=None, body=None, **kw):
        self.action = "fulfill"
        self.fulfilled = (status, headers or {}, body)


def _fake_playwright(monkeypatch, routes_to_play):
    """A fake sync_playwright: records launch args and the registered route
    handler, then plays ``routes_to_play`` through it during goto()."""
    seen = {"launch": None, "handler": None, "played": []}

    class Page:
        def route(self, pattern, handler):
            seen["handler"] = handler

        def goto(self, *a, **k):
            for r in routes_to_play:
                seen["handler"](r)
                seen["played"].append(r)

        def wait_for_timeout(self, *a):
            pass

        def content(self):
            return "<html>ok</html>"

    class Ctx:
        def route(self, pattern, handler):
            seen["handler"] = handler

        def route_web_socket(self, pattern, handler):
            seen["ws"] = handler

        def new_page(self):
            return Page()

    class Browser:
        def new_context(self, **k):
            seen["context"] = k
            return Ctx()

        def close(self):
            pass

    class Chromium:
        def launch(self, **kw):
            seen["launch"] = kw
            return Browser()

    class PW:
        chromium = Chromium()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    fake = types.ModuleType("playwright.sync_api")
    fake.sync_playwright = PW
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake)
    return seen


def test_render_subresource_on_rebinding_host_is_fetched_from_checked_address(monkeypatch):
    """A hostile DNS server answers PUBLIC on the first lookup of each host and
    PRIVATE (10.0.0.5) after. Old code checked a sub-resource's host and then
    told Chromium to continue, so Chromium looked it up again and got 10.0.0.5.
    Now every request is fetched by Harrier from the address it checked."""
    first = {"site.example": "93.184.216.34", "cdn.example": "93.184.216.35"}
    lookups: dict[str, int] = {}

    def fake_getaddrinfo(host, *a, **k):
        try:
            ipaddress.ip_address(host)
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, 0))]
        except ValueError:
            pass
        if host not in first:
            raise socket.gaierror("nx")
        lookups[host] = lookups.get(host, 0) + 1
        ip = first[host] if lookups[host] == 1 else "10.0.0.5"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    connected = []
    socks = []

    def fake_create_connection(address, *a, **k):
        connected.append(address)
        body = b"/* js */" if address[0] == "93.184.216.35" else b"<html>page</html>"
        s = _FakeSock(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n"
                      b"Content-Length: %d\r\n\r\n" % len(body) + body)
        socks.append(s)
        return s

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(socket, "create_connection", fake_create_connection)

    doc = _Route("https://site.example/p")
    js1 = _Route("http://cdn.example/app.js", resource_type="script")
    js2 = _Route("http://cdn.example/app2.js", resource_type="script")
    internal = _Route("http://169.254.169.254/latest/", resource_type="xhr")
    seen = _fake_playwright(monkeypatch, [doc, js1, js2, internal])

    # https would need real TLS; make the pinned HTTPS connection plain for the fake.
    class PlainPinned(verify._PinnedHTTPConnection):
        def __init__(self, host, port, ip, **kw):
            kw.pop("context", None)
            super().__init__(host, port, ip, **kw)

    monkeypatch.setattr(verify, "_PinnedHTTPSConnection", PlainPinned)

    assert verify._render_page("https://site.example/p") == "<html>ok</html>"

    # Chromium was never told to make a request itself.
    assert [r.action for r in seen["played"]] == ["fulfill", "fulfill", "fulfill", "abort"]
    assert doc.fulfilled[0] == 200 and doc.fulfilled[2] == b"<html>page</html>"
    assert js2.fulfilled[2] == b"/* js */"
    # Every connection went to an address that was checked; never 10.0.0.5.
    assert connected == [("93.184.216.34", 443), ("93.184.216.35", 80),
                         ("93.184.216.35", 80)]
    # The Host header is the request's own host, not a forwarded one.
    assert b"Host: cdn.example" in socks[1].sent
    assert b"spoofed" not in b"".join(s.sent for s in socks)
    # Chromium's own resolver resolves nothing.
    args = seen["launch"]["args"]
    assert "--host-resolver-rules=MAP * ~NOTFOUND" in args


def test_render_router_refuses_non_http_and_blocked_types(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **k: (_ for _ in ()).throw(socket.gaierror("nx")))
    router = verify._RenderRouter({}, deadline=None)
    for url in ("file:///etc/passwd", "http://127.0.0.1/", "http://nx.example/",
                "data:text/html,hi"):
        r = _Route(url)
        router(r)
        assert r.action == "abort", url


def test_render_router_stops_after_request_budget(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda h, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                                             ("93.184.216.34", 0))])
    ok = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: _FakeSock(ok))
    router = verify._RenderRouter({}, deadline=None, max_requests=2)
    results = []
    for i in range(3):
        r = _Route(f"http://a.example/{i}", resource_type="xhr")
        router(r)
        results.append(r.action)
    assert results == ["fulfill", "fulfill", "abort"]


def test_render_router_drops_oversized_response(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda h, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                                             ("93.184.216.34", 0))])
    big = b"x" * (verify._RENDER_MAX_BODY + 10)
    resp = b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n" % len(big) + big
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: _FakeSock(resp))
    router = verify._RenderRouter({}, deadline=None)
    r = _Route("http://a.example/huge", resource_type="xhr")
    router(r)
    assert r.action == "abort"


def test_render_router_follows_redirects_itself_checking_each_hop(monkeypatch):
    """Playwright routes only the first request of a redirect chain, so a 3xx
    handed to Chromium would be followed unrouted. The router follows it, and
    each hop is checked and pinned; a hop to a private host is refused."""
    ips = {"a.example": "93.184.216.34", "other.example": "93.184.216.35",
           "internal.example": "10.1.2.3"}
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda h, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                                             (ips[h], 0))])
    replies = {
        ("93.184.216.34", "/u"): b"HTTP/1.1 302 Found\r\nLocation: http://other.example/x\r\n"
                                 b"Content-Length: 0\r\n\r\n",
        ("93.184.216.34", "/bad"): b"HTTP/1.1 302 Found\r\nLocation: http://internal.example/\r\n"
                                   b"Content-Length: 0\r\n\r\n",
        ("93.184.216.35", "/x"): b"HTTP/1.1 200 OK\r\nSet-Cookie: a=1\r\nSet-Cookie: b=2\r\n"
                                 b"Content-Length: 4\r\n\r\nhere",
    }
    connected = []

    class Sock(_FakeSock):
        def __init__(self, ip):
            super().__init__(b"")
            self.ip = ip

        def makefile(self, *a, **k):
            path = self.sent.split(b" ")[1].decode()
            return self._io.BytesIO(replies[(self.ip, path)])

    monkeypatch.setattr(socket, "create_connection",
                        lambda addr, *a, **k: connected.append(addr) or Sock(addr[0]))
    router = verify._RenderRouter({}, deadline=None)
    r = _Route("http://a.example/u", resource_type="script")
    router(r)
    status, headers, body = r.fulfilled
    assert (status, body) == (200, b"here")
    assert headers["set-cookie"] == "a=1\nb=2"
    assert connected == [("93.184.216.34", 80), ("93.184.216.35", 80)]

    connected.clear()
    bad = _Route("http://a.example/bad", resource_type="script")
    router(bad)
    assert bad.action == "abort"
    assert connected == [("93.184.216.34", 80)]


# --- integration: real Chromium, hostile Chromium resolver -------------------

def _chromium_path():
    for p in (os.environ.get("HARRIER_TEST_CHROMIUM"), shutil.which("chromium"),
              shutil.which("chromium-browser"), shutil.which("google-chrome")):
        if p and os.path.exists(p):
            return p
    return None


def _playwright_ok():
    try:
        import playwright.sync_api  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


_PUBLIC_PAGES = {
    ("main.example", "/u/alice"): (302, {"Location": "http://profile.example/alice"}, b""),
    ("profile.example", "/alice"): (200, {"Content-Type": "text/html"}, (
        b"<html><head><title>Alice Wademan</title>"
        b'<script src="http://cdn.example/app.js"></script></head>'
        b"<body><h1>Alice Wademan</h1><div id=loc></div></body></html>")),
    ("cdn.example", "/app.js"): (200, {"Content-Type": "application/javascript"}, (
        b"fetch('http://api.example/data').then(r => r.text())"
        b".then(t => { document.getElementById('loc').textContent = t; });")),
    ("api.example", "/data"): (200, {"Content-Type": "text/plain",
                                     "Access-Control-Allow-Origin": "*"},
                               b"Lives in Springfield"),
}

_PUBLIC_IPS = {"main.example": "93.184.216.34", "profile.example": "93.184.216.35",
               "cdn.example": "93.184.216.36", "api.example": "93.184.216.37"}


def _serve(handler_cls):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def two_servers():
    internal_hits = []

    class Public(BaseHTTPRequestHandler):
        def do_GET(self):
            host = (self.headers.get("Host") or "").split(":")[0]
            page = _PUBLIC_PAGES.get((host, self.path))
            if page is None:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            status, headers, body = page
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    class Internal(BaseHTTPRequestHandler):
        def _hit(self):
            internal_hits.append((self.command, self.headers.get("Host"), self.path))
            body = b"<html><body>SECRET-INTERNAL</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = do_POST = do_CONNECT = _hit

        def log_message(self, *a):
            pass

    pub, internal = _serve(Public), _serve(Internal)
    yield pub.server_address[1], internal.server_address[1], internal_hits
    pub.shutdown()
    internal.shutdown()


def _hostile_launch(monkeypatch, chromium, public_port, internal_port, keep_killswitch):
    """Run the real browser, but make Chromium's resolver hostile: the code's
    explicit pins to a checked public address are honoured (sent to the local
    "public" server); every other name resolves to the "internal" server.
    Every other --host-resolver-rules entry the code passes is dropped, so the
    test does not depend on it."""
    from playwright.sync_api._generated import BrowserType

    real_launch = BrowserType.launch

    def launch(self, **kw):
        pins = []
        args = []
        for a in kw.get("args") or []:
            if a.startswith("--host-resolver-rules="):
                for rule in a.split("=", 1)[1].split(","):
                    parts = rule.split()
                    if len(parts) == 3 and parts[0] == "MAP" and parts[2] in _PUBLIC_IPS.values():
                        pins.append(f"MAP {parts[1]} 127.0.0.1:{public_port}")
                continue
            if not keep_killswitch and a.startswith(("--proxy-server", "--proxy-bypass-list")):
                continue
            args.append(a)
        args.append("--host-resolver-rules=" + ", ".join(
            pins + [f"MAP * 127.0.0.1:{internal_port}", "EXCLUDE 127.0.0.1"]))
        kw["args"] = args
        kw["executable_path"] = chromium
        return real_launch(self, **kw)

    monkeypatch.setattr(BrowserType, "launch", launch)


@pytest.mark.skipif(not _playwright_ok() or _chromium_path() is None,
                    reason="needs playwright and a local Chromium")
@pytest.mark.parametrize("keep_killswitch", [True, False],
                         ids=["with-proxy-killswitch", "interception-only"])
def test_real_chromium_never_connects_on_its_own(monkeypatch, two_servers, keep_killswitch):
    public_port, internal_port, internal_hits = two_servers

    real_getaddrinfo = socket.getaddrinfo

    def fake_getaddrinfo(host, *a, **k):
        try:
            ipaddress.ip_address(host)
            return real_getaddrinfo(host, *a, **k)  # literals: no DNS involved
        except ValueError:
            pass
        if host not in _PUBLIC_IPS:
            raise socket.gaierror("nx")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (_PUBLIC_IPS[host], 0))]

    def fake_create_connection(address, *a, **k):
        if address[0] in _PUBLIC_IPS.values():
            return _REAL_CREATE_CONNECTION(("127.0.0.1", public_port), *a, **k)
        raise OSError(f"test: refusing connect to {address}")

    monkeypatch.setattr(verify.socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(verify.socket, "create_connection", fake_create_connection)
    _hostile_launch(monkeypatch, _chromium_path(), public_port, internal_port,
                    keep_killswitch)

    html = verify._render_page("http://main.example/u/alice", timeout=15)

    page_hits = [h for h in internal_hits if (h[1] or "").split(":")[0] in _PUBLIC_IPS]
    assert page_hits == []
    if keep_killswitch:
        # With the dead proxy, Chromium's own background traffic (time sync,
        # component updates: requests no page made, so never routed) is
        # stopped too.
        assert internal_hits == []
    assert html is not None
    assert "SECRET-INTERNAL" not in html
    # Normal rendering still works across a cross-host redirect, an external
    # script and a cross-origin XHR.
    assert "Alice Wademan" in html
    assert "Lives in Springfield" in html
