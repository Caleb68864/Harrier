"""Tests for the consent-gated people-search adapter (SS-04).

No test performs a real network call. The consent gate is verified by asserting
Playwright is never even imported/invoked; the block path is verified with a
simulated 403/Cloudflare response.
"""

from harrier.adapters import people_search
from harrier.schema import Finding


def test_consent_gate_blocks_and_makes_no_network_call(monkeypatch):
    """consent=False → status=blocked, blocked Finding, NO fetch attempted."""
    called = {"fetch": False}

    def boom(*a, **k):
        called["fetch"] = True
        raise AssertionError("no network call must happen without consent")

    monkeypatch.setattr(people_search, "_fetch", boom)
    res = people_search.run("John Smith", consent=False)

    assert res["status"] == "blocked"
    assert called["fetch"] is False
    assert len(res["findings"]) == 1
    f = res["findings"][0]
    assert isinstance(f, Finding)
    assert f.tier == "blocked"
    assert "consent" in (f.reason or "").lower()


def test_block_on_403_returns_blocked_finding_no_raise(monkeypatch):
    """A simulated 403 → blocked Finding with a manual-step reason, no raise."""
    monkeypatch.setattr(people_search, "_fetch",
                        lambda *a, **k: (403, "<html>Access denied</html>"))
    res = people_search.run("John Smith", consent=True, _sleep=False)

    assert res["status"] == "blocked"
    assert len(res["findings"]) == 1
    f = res["findings"][0]
    assert f.tier == "blocked"
    assert "manual step" in (f.reason or "").lower()


def test_block_on_cloudflare_challenge(monkeypatch):
    """A 200 that is actually a Cloudflare 'Just a moment' page is blocked."""
    monkeypatch.setattr(
        people_search, "_fetch",
        lambda *a, **k: (200, "<title>Just a moment...</title>"),
    )
    res = people_search.run("Jane Doe", consent=True, _sleep=False)
    assert res["status"] == "blocked"
    assert res["findings"][0].tier == "blocked"


def test_browser_error_degrades_to_unavailable(monkeypatch):
    monkeypatch.setattr(people_search, "_fetch", lambda *a, **k: ("ERROR", ""))
    res = people_search.run("John Smith", consent=True, _sleep=False)
    assert res["status"] == "unavailable"
    assert res["findings"][0].tier == "blocked"


def test_unblocked_page_parses_scrape_tier(monkeypatch):
    """If a page ever comes back clean, it yields a scrape-tier Finding."""
    monkeypatch.setattr(
        people_search, "_fetch",
        lambda *a, **k: (200, "<html><body>real record content here</body></html>"),
    )
    res = people_search.run("John Smith", consent=True, _sleep=False)
    assert res["status"] == "ok"
    assert res["findings"][0].tier == "scrape"


def test_empty_name_is_error():
    res = people_search.run("", consent=True, _sleep=False)
    assert res["status"] == "error"
    assert res["findings"] == []
