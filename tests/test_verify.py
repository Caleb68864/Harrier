"""Tests for the profile verification stage (Phase 3b). Fetch is mocked."""

import harrier.verify as verify
from harrier.schema import Finding
from harrier.verify import verify_finding, verify_findings

ANCHOR = {
    "name": "Amanda Bennett", "first": "amanda", "last": "bennett",
    "maiden": "wademan", "married": "warm", "city": "Harvard", "state": "Nebraska",
}


def _f(url="https://site/amandawademan", selector="amandawademan"):
    return Finding(selector=selector, source_tool="sherlock", url=url,
                   value=url, exists=True, confidence="medium")


def test_dead_profile_marked_false_positive(monkeypatch):
    monkeypatch.setattr(verify, "_fetch", lambda url, timeout=10: (404, ""))
    f = verify_finding(_f(), ANCHOR)
    assert f.exists is False
    assert f.confidence == "low"
    assert f.raw["verify"]["verdict"] == "false_positive"


def test_unreachable_left_unverified(monkeypatch):
    monkeypatch.setattr(verify, "_fetch", lambda url, timeout=10: (403, ""))
    f = verify_finding(_f(), ANCHOR)
    assert f.raw["verify"]["verdict"] == "unverifiable"
    assert f.confidence == "medium"  # unchanged — we couldn't check


def test_corroboration_promotes_to_high(monkeypatch):
    body = "<title>Amanda Wademan</title> profile — lives in Nebraska"
    monkeypatch.setattr(verify, "_fetch", lambda url, timeout=10: (200, body))
    f = verify_finding(_f(), ANCHOR)
    assert f.raw["verify"]["verdict"] == "corroborated"
    assert f.confidence == "high"
    assert "wademan" in f.raw["verify"]["matched"]


def test_handle_echo_does_not_self_corroborate(monkeypatch):
    # page only echoes the concatenated handle → no standalone-word match
    body = "<title>amandawademan (u/amandawademan) - Reddit</title>"
    monkeypatch.setattr(verify, "_fetch", lambda url, timeout=10: (200, body))
    f = verify_finding(_f(), ANCHOR)
    assert f.raw["verify"]["verdict"] == "reachable_no_corroboration"
    assert f.confidence == "medium"  # unchanged, not falsely promoted


def test_soft_404_detected_despite_200(monkeypatch):
    body = "<title>Spotify</title> Sorry, we couldn't find that page. Page not found."
    monkeypatch.setattr(verify, "_fetch", lambda url, timeout=10: (200, body))
    f = verify_finding(_f(), ANCHOR)
    assert f.exists is False
    assert f.raw["verify"]["verdict"] == "false_positive"


def test_js_shell_marked_unverifiable(monkeypatch):
    # 200, no anchor tokens, handle not present -> JS shell -> unverifiable
    body = "<title>Spotify - Web Player</title> loading application"
    monkeypatch.setattr(verify, "_fetch", lambda url, timeout=10: (200, body))
    f = verify_finding(_f(), ANCHOR)
    assert f.raw["verify"]["verdict"] == "unverifiable"


def test_render_fallback_upgrades_unverifiable(monkeypatch):
    # plain fetch returns a JS shell (unverifiable); render returns readable text
    monkeypatch.setattr(verify, "_fetch", lambda url, timeout=10: (200, "<title>App</title> loading"))
    monkeypatch.setattr(verify, "_render_page",
                        lambda url, timeout=20: "<title>Amanda Wademan</title> lives in Nebraska")
    f = verify_finding(_f(), ANCHOR, render_fn=verify._render_page)
    assert f.raw["verify"]["verdict"] == "corroborated"
    assert f.raw["verify"]["rendered"] is True
    assert f.confidence == "high"


def test_render_fallback_only_when_unverifiable(monkeypatch):
    # a hard 404 is decided without rendering — render must not be consulted
    monkeypatch.setattr(verify, "_fetch", lambda url, timeout=10: (404, ""))
    def _boom(url, timeout=20):  # would fail the test if called
        raise AssertionError("render should not run on a hard 404")
    f = verify_finding(_f(), ANCHOR, render_fn=_boom)
    assert f.raw["verify"]["verdict"] == "false_positive"


def test_verify_findings_reports_stats(monkeypatch):
    monkeypatch.setattr(verify, "_fetch", lambda url, timeout=10: (404, ""))
    out, stats = verify_findings([_f(url="https://s/1"), _f(url="https://s/2")], ANCHOR,
                                 render=False)
    assert stats["verified"] == 2
    assert stats["false_positive"] == 2
