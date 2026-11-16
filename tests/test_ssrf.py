"""SSRF guard for verify: loopback / private / link-local / metadata addresses
are refused on the resolved host AND on every redirect hop. No real network."""

import io
import ipaddress
import socket

import pytest

from harrier import verify


def _resolve_to(monkeypatch, mapping):
    def fake_getaddrinfo(host, *a, **k):
        if host not in mapping:
            raise socket.gaierror("nx")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in mapping[host]]

    monkeypatch.setattr(verify.socket, "getaddrinfo", fake_getaddrinfo)


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.0.1",
                                "169.254.169.254", "100.64.0.1", "0.0.0.0", "::1",
                                "fe80::1", "fd00::1", "::ffff:127.0.0.1", "224.0.0.1"])
def test_non_public_ips_refused(ip):
    assert verify._ip_is_public(ip) is False


def test_public_ip_allowed():
    assert verify._ip_is_public("93.184.216.34") is True


def test_hostname_resolving_to_private_is_refused(monkeypatch):
    _resolve_to(monkeypatch, {"evil.example": ["10.0.0.5"],
                              "mixed.example": ["93.184.216.34", "127.0.0.1"],
                              "ok.example": ["93.184.216.34"]})
    assert not verify._is_public_http_url("https://evil.example/x")
    assert not verify._is_public_http_url("https://mixed.example/x")  # any private record
    assert not verify._is_public_http_url("https://nxdomain.example/x")
    assert verify._is_public_http_url("https://ok.example/x")


def test_fetch_never_opens_private_target(monkeypatch):
    _resolve_to(monkeypatch, {"metadata.example": ["169.254.169.254"]})
    opened = []
    monkeypatch.setattr(socket, "create_connection",
                        lambda *a, **k: opened.append(a) or (_ for _ in ()).throw(OSError()))
    assert verify._fetch("http://metadata.example/latest/meta-data/")[:2] == (0, "")
    assert verify._fetch("http://127.0.0.1:8080/admin")[:2] == (0, "")
    assert opened == []


# --- O1b: DNS rebinding -----------------------------------------------------
# A fake resolver answers PUBLIC on the first lookup of a host and PRIVATE on
# every later one (a hostile DNS server with TTL 0). A fake create_connection
# stands in for the network: it resolves exactly the way the real one does
# (via getaddrinfo, so an unpinned connect sees the second, private answer),
# records the address it would connect to, and serves a canned HTTP response.

class _FakeSock:
    def __init__(self, response: bytes):
        self._response = response
        self.sent = b""

    def sendall(self, data):
        self.sent += data

    def makefile(self, *a, **k):
        return io.BytesIO(self._response)

    def setsockopt(self, *a, **k):
        pass

    def settimeout(self, *a, **k):
        pass

    def close(self):
        pass


def _rebinding_net(monkeypatch, first_answers, responses):
    """first_answers: host -> public IP for lookup #1 (later lookups: 10.0.0.5).
    responses: ip -> raw HTTP response bytes."""
    calls: dict[str, int] = {}
    connected: list[str] = []
    socks: list[_FakeSock] = []

    def fake_getaddrinfo(host, *a, **k):
        try:
            ipaddress.ip_address(host)
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, 0))]
        except ValueError:
            pass
        if host not in first_answers:
            raise socket.gaierror("nx")
        calls[host] = calls.get(host, 0) + 1
        ip = first_answers[host] if calls[host] == 1 else "10.0.0.5"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    def fake_create_connection(address, *a, **k):
        host, port = address
        ip = fake_getaddrinfo(host, port)[0][4][0]
        connected.append(ip)
        sock = _FakeSock(responses.get(ip, b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\n\r\nINTERNAL"))
        socks.append(sock)
        return sock

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(socket, "create_connection", fake_create_connection)
    return connected, socks


_OK = b"HTTP/1.1 200 OK\r\nContent-Length: 7\r\n\r\nprofile"


def test_rebinding_connect_uses_the_checked_address(monkeypatch):
    connected, socks = _rebinding_net(monkeypatch, {"rebind.example": "93.184.216.34"},
                                      {"93.184.216.34": _OK})
    status, body = verify._fetch("http://rebind.example/u")[:2]
    assert connected == ["93.184.216.34"]  # never the rebound 10.0.0.5
    assert (status, body) == (200, "profile")
    assert b"Host: rebind.example" in socks[0].sent  # Host header keeps the name


def test_rebinding_on_redirect_hop_is_refused(monkeypatch):
    redirect = (b"HTTP/1.1 302 Found\r\nLocation: http://second.example/v\r\n"
                b"Content-Length: 0\r\n\r\n")
    connected, socks = _rebinding_net(
        monkeypatch,
        {"first.example": "93.184.216.34", "second.example": "93.184.216.35"},
        {"93.184.216.34": redirect, "93.184.216.35": _OK})
    status, body = verify._fetch("http://first.example/u")[:2]
    assert "10.0.0.5" not in connected
    assert connected == ["93.184.216.34", "93.184.216.35"]
    assert (status, body) == (200, "profile")
    assert b"Host: second.example" in socks[1].sent


def test_redirect_to_private_host_is_not_connected(monkeypatch):
    redirect = (b"HTTP/1.1 301 Moved\r\nLocation: http://169.254.169.254/latest/\r\n"
                b"Content-Length: 0\r\n\r\n")
    connected, _ = _rebinding_net(monkeypatch, {"first.example": "93.184.216.34"},
                                  {"93.184.216.34": redirect})
    assert verify._fetch("http://first.example/u")[0] == 0
    assert connected == ["93.184.216.34"]


def test_redirect_loop_is_bounded(monkeypatch):
    loop = (b"HTTP/1.1 302 Found\r\nLocation: /again\r\nContent-Length: 0\r\n\r\n")
    _resolve_to(monkeypatch, {"loop.example": ["93.184.216.34"]})
    n = []
    monkeypatch.setattr(socket, "create_connection",
                        lambda *a, **k: n.append(1) or _FakeSock(loop))
    assert verify._fetch("http://loop.example/")[0] == 0
    assert len(n) == verify._MAX_REDIRECTS + 1


def test_https_pins_address_but_keeps_sni(monkeypatch):
    connected = []
    monkeypatch.setattr(socket, "create_connection",
                        lambda addr, *a, **k: connected.append(addr) or _FakeSock(b""))

    class Ctx:
        check_hostname = True
        post_handshake_auth = None
        verify_mode = None

        def wrap_socket(self, sock, server_hostname=None):
            self.sni = server_hostname
            return sock

    ctx = Ctx()
    conn = verify._PinnedHTTPSConnection("site.example", 443, "93.184.216.34", context=ctx)
    conn.connect()
    assert connected == [("93.184.216.34", 443)]
    assert ctx.sni == "site.example"


def test_redirect_hop_to_private_or_non_http_is_refused(monkeypatch):
    for bad in (b"http://169.254.169.254/latest/", b"https://internal.example/",
                b"ftp://ok.example/x", b"file:///etc/passwd"):
        _resolve_to(monkeypatch, {"ok.example": ["93.184.216.34"],
                                  "internal.example": ["192.168.0.10"]})
        connected = []
        resp = (b"HTTP/1.1 302 Found\r\nLocation: " + bad +
                b"\r\nContent-Length: 0\r\n\r\n")
        monkeypatch.setattr(socket, "create_connection",
                            lambda addr, *a, **k: connected.append(addr) or _FakeSock(resp))
        assert verify._fetch("http://ok.example/u")[0] == 0, bad
        assert connected == [("93.184.216.34", 80)], bad


def test_render_refuses_private_target_and_route_guard_aborts(monkeypatch):
    _resolve_to(monkeypatch, {"ok.example": ["93.184.216.34"]})
    assert verify._render_page("http://127.0.0.1/") is None

    class Route:
        def __init__(self, url):
            self.request = type("R", (), {"url": url})()
            self.action = None

        def continue_(self):
            self.action = "continue"

        def abort(self):
            self.action = "abort"

    for url, want in (("https://ok.example/p", "continue"),
                      ("http://169.254.169.254/", "abort"),
                      ("http://localhost/", "abort")):
        r = Route(url)
        verify._route_guard(r)
        assert r.action == want, url


def test_render_pins_main_host_in_chromium(monkeypatch):
    import sys
    import types

    _resolve_to(monkeypatch, {"site.example": ["93.184.216.34"]})
    launched = {}

    class Page:
        def route(self, *a): pass
        def goto(self, *a, **k): pass
        def wait_for_timeout(self, *a): pass
        def content(self): return "<html>ok</html>"

    class Browser:
        def new_context(self, **k): return types.SimpleNamespace(new_page=Page)
        def close(self): pass

    class Chromium:
        def launch(self, **kw):
            launched.update(kw)
            return Browser()

    class PW:
        chromium = Chromium()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    fake = types.ModuleType("playwright.sync_api")
    fake.sync_playwright = PW
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake)
    assert verify._render_page("https://site.example/p") == "<html>ok</html>"
    assert "--host-resolver-rules=MAP site.example 93.184.216.34" in launched.get("args", [])
