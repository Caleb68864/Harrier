"""Tests for the investigation loop (CoAnalyst360 shape). Tools stubbed."""

import harrier.investigate as inv
from harrier.adapters import AdapterResult
from harrier.schema import Finding


def _sweep_result(findings):
    return {"findings": findings, "sources": [], "candidates": [],
            "suppressed": 0, "verify": None, "manual_assist": []}


def _empty_court(name, state=None):
    return AdapterResult(status="empty", tool="courtlistener")


def test_single_round_when_no_refinement_fuel(monkeypatch):
    f = Finding(selector="awademan", source_tool="sherlock",
                url="https://x/awademan", value="x", exists=True, confidence="medium")
    monkeypatch.setattr(inv.sweep_mod, "person_sweep", lambda *a, **k: _sweep_result([f]))
    monkeypatch.setattr(inv.court_mod, "run", _empty_court)
    res = inv.investigate("Amanda Bennett", maiden="Wademan")
    assert res["rounds_run"] == 1
    assert res["discovered"] == []
    assert any(x.source_tool == "sherlock" for x in res["findings"])


def test_refinement_runs_second_round_on_discovered_surname(monkeypatch):
    calls = {"n": 0}

    def sweep(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            f = Finding(selector="awademan", source_tool="maigret",
                        url="https://x/awademan", value="x", exists=True,
                        confidence="high",
                        raw={"ids": {"fullname": "Amanda Kowalski"},
                             "verify": {"verdict": "corroborated"}})
            return _sweep_result([f])
        return _sweep_result([])

    monkeypatch.setattr(inv.sweep_mod, "person_sweep", sweep)
    monkeypatch.setattr(inv.court_mod, "run", _empty_court)
    res = inv.investigate("Amanda Bennett", maiden="Wademan", max_rounds=2)
    assert res["rounds_run"] == 2
    assert "kowalski" in res["discovered"]


def test_next_steps_from_blocked_and_unverifiable(monkeypatch):
    blocked = Finding(selector="Amanda Bennett", source_tool="people_search",
                      url="https://tps/", tier="blocked", reason="open in browser")
    unver = Finding(selector="awademan", source_tool="sherlock",
                    url="https://x/awademan", confidence="medium",
                    raw={"verify": {"verdict": "unverifiable"}})
    monkeypatch.setattr(inv.sweep_mod, "person_sweep",
                        lambda *a, **k: _sweep_result([blocked, unver]))
    monkeypatch.setattr(inv.court_mod, "run", _empty_court)
    res = inv.investigate("Amanda Bennett")
    joined = " ".join(res["next_steps"])
    assert "open in browser" in joined
    assert "https://x/awademan" in joined
    assert res["manual_assist"]  # always hands back the pre-filled links
