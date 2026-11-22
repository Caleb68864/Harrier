"""Items the agent decided on 2026-11-21 under the owner's standing order
(roadmap O22-O26, O30-O32; the owner may revisit each)."""

import pytest

from harrier.adapters import court


# --- O23: no CourtListener token -> skip, with a reason, and no request -------

def test_court_without_token_makes_no_request(monkeypatch):
    monkeypatch.delenv("COURTLISTENER_TOKEN", raising=False)
    monkeypatch.delenv("HARRIER_COURT_ANONYMOUS", raising=False)

    def boom(*a, **k):
        raise AssertionError("no request without a token")

    monkeypatch.setattr(court, "_fetch", boom)
    res = court.run("Amanda Bennett")
    assert res.status == "unavailable" and res == []
    assert "COURTLISTENER_TOKEN" in res.reason
    assert "skipped" in res.reason and "manual_assist" in res.reason


def test_court_anonymous_setting_still_tries(monkeypatch):
    # HARRIER_COURT_ANONYMOUS=1 restores the old behaviour (in case
    # CourtListener reopens anonymous access).
    monkeypatch.delenv("COURTLISTENER_TOKEN", raising=False)
    monkeypatch.setenv("HARRIER_COURT_ANONYMOUS", "1")
    calls = []
    monkeypatch.setattr(court, "_fetch", lambda q, t: calls.append(q) or (200, {"results": []}))
    assert court.run("Amanda Bennett").status == "empty"
    assert calls == ['"Amanda Bennett"']


def test_court_with_token_queries(monkeypatch):
    monkeypatch.setenv("COURTLISTENER_TOKEN", "x")
    monkeypatch.delenv("HARRIER_COURT_ANONYMOUS", raising=False)
    calls = []
    monkeypatch.setattr(court, "_fetch", lambda q, t: calls.append(q) or (200, {"results": []}))
    court.run("Amanda Bennett")
    assert calls
