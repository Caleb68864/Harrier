"""A render that cannot run says so (found 2026-11-21).

On this host Harrier's Playwright wanted chromium_headless_shell-1228, which
was not installed: every render fallback raised "Executable doesn't exist",
_render_page swallowed it and returned None, and the finding stayed
"unverifiable" with no hint that the render never happened.
"""

import logging
import sys
import types

import pytest

from harrier import verify
from harrier.schema import Finding

ANCHOR = {"name": "Amanda Wademan", "first": "Amanda", "last": "Wademan"}


def _broken_playwright(monkeypatch, exc):
    class Chromium:
        def launch(self, **kw):
            raise exc

    class PW:
        chromium = Chromium()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    fake = types.ModuleType("playwright.sync_api")
    fake.sync_playwright = PW
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake)
    monkeypatch.setattr(verify, "_pinned_target",
                        lambda url: ("https", "site.example", 443, "93.184.216.34"))
    monkeypatch.setattr(verify._RenderRouter, "fetch",
                        lambda self, m, url, h, b: (200, {}, b"<html></html>", url))


def test_render_page_raises_render_unavailable_with_the_cause(monkeypatch, caplog):
    _broken_playwright(monkeypatch, RuntimeError(
        "BrowserType.launch: Executable doesn't exist at /x/chrome-headless-shell"))
    with caplog.at_level(logging.WARNING, logger="harrier.verify"):
        with pytest.raises(verify.RenderUnavailable, match="Executable doesn't exist"):
            verify._render_page("https://site.example/amandawademan")
    assert any("render unavailable" in r.getMessage() for r in caplog.records)


def test_refused_url_is_still_just_none():
    assert verify._render_page("http://127.0.0.1/") is None


def test_verify_finding_reports_the_render_failure(monkeypatch):
    monkeypatch.setattr(verify, "_fetch", lambda url, timeout=10: (200, "<title>App</title>"))

    def render(url):
        raise verify.RenderUnavailable("Executable doesn't exist at /x")

    f = Finding(selector="amandawademan", source_tool="sherlock",
                url="https://site.example/amandawademan", exists=True)
    verify.verify_finding(f, ANCHOR, render_fn=render)
    v = f.raw["verify"]
    assert v["verdict"] == "unverifiable" and v["rendered"] is False
    assert "Executable doesn't exist" in v["render_error"]
    assert "render unavailable" in f.reason


def test_verify_findings_counts_render_failures(monkeypatch):
    monkeypatch.setattr(verify, "_fetch", lambda url, timeout=10: (200, "<title>App</title>"))

    def boom(url, timeout=20):
        raise verify.RenderUnavailable("no browser")

    monkeypatch.setattr(verify, "_render_page", boom)
    fs = [Finding(selector="amandawademan", source_tool="sherlock",
                  url=f"https://s{i}.example/amandawademan",
                  exists=True) for i in range(2)]
    _, stats = verify.verify_findings(fs, ANCHOR)
    assert stats["render_failed"] == 2 and stats["rendered"] == 0
