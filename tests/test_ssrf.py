"""SSRF guard for verify: loopback / private / link-local / metadata addresses
are refused on the resolved host AND on every redirect hop. No real network."""

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
    monkeypatch.setattr(verify._OPENER, "open", lambda *a, **k: opened.append(a))
    assert verify._fetch("http://metadata.example/latest/meta-data/") == (0, "")
    assert verify._fetch("http://127.0.0.1:8080/admin") == (0, "")
    assert opened == []


def test_redirect_hop_to_private_is_refused(monkeypatch):
    import urllib.error
    import urllib.request

    _resolve_to(monkeypatch, {"ok.example": ["93.184.216.34"],
                              "internal.example": ["192.168.0.10"]})
    h = verify._GuardedRedirectHandler()
    req = urllib.request.Request("https://ok.example/u")
    for bad in ("http://169.254.169.254/latest/", "https://internal.example/",
                "ftp://ok.example/x", "file:///etc/passwd"):
        with pytest.raises(urllib.error.HTTPError):
            h.redirect_request(req, None, 302, "Found", {}, bad)
    assert h.redirect_request(req, None, 302, "Found", {}, "https://ok.example/v") is not None


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
