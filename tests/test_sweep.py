"""Tests for the fan-out runner, correlator, and person_sweep (SS-05).

Adapters are stubbed with fixtures — no real tools or network. Verifies the
integration seam, cross-source confidence, the concurrency cap, and the
all-unavailable degradation path (A-3).
"""

import asyncio

import pytest

from harrier import sweep
from harrier.adapters import AdapterResult
from harrier.correlate import correlate
from harrier.runner import DEFAULT_MAX_CONCURRENCY, run_jobs
from harrier.schema import Finding


# --- correlator ---------------------------------------------------------------

def test_confidence_high_when_two_sources_agree():
    findings = [
        Finding(selector="a", source_tool="sherlock", value="github.com/a", exists=True),
        Finding(selector="a", source_tool="maigret", value="github.com/a", exists=True),
    ]
    out = correlate(findings)
    assert all(f.confidence == "high" for f in out)
    # deduped to distinct sources
    assert len(out) == 2


def test_confidence_low_when_single_source():
    findings = [
        Finding(selector="a", source_tool="sherlock", value="github.com/a", exists=True),
    ]
    out = correlate(findings)
    assert len(out) == 1
    assert out[0].confidence == "low"


def test_correlate_passes_through_blocked():
    findings = [
        Finding(selector="x", source_tool="people_search", tier="blocked",
                reason="manual step", value=None),
    ]
    out = correlate(findings)
    assert len(out) == 1
    assert out[0].tier == "blocked"


def test_correlate_drops_intra_tool_duplicates():
    findings = [
        Finding(selector="a", source_tool="sherlock", value="github.com/a"),
        Finding(selector="a", source_tool="sherlock", value="github.com/a"),
    ]
    out = correlate(findings)
    assert len(out) == 1


# --- runner -------------------------------------------------------------------

def test_runner_enforces_concurrency_cap():
    """No more than max_concurrency jobs run at once."""
    state = {"active": 0, "peak": 0}

    def job():
        state["active"] += 1
        state["peak"] = max(state["peak"], state["active"])
        # busy-wait a touch so overlap is observable
        for _ in range(10000):
            pass
        state["active"] -= 1
        return AdapterResult([], status="ok", tool="t")

    jobs = [("t", job) for _ in range(20)]
    asyncio.run(run_jobs(jobs, max_concurrency=3, jitter=0))
    assert state["peak"] <= 3


def test_runner_captures_exceptions_without_raising():
    def boom():
        raise RuntimeError("kaboom")

    out = asyncio.run(run_jobs([("t", boom)], jitter=0))
    assert isinstance(out[0][1], RuntimeError)


def test_default_cap_is_bounded():
    assert DEFAULT_MAX_CONCURRENCY >= 1


# --- person_sweep integration -------------------------------------------------

def _stub(monkeypatch, *, username_findings=None, all_unavailable=False):
    def uname(sel, *a, **k):
        if all_unavailable:
            return AdapterResult(status="unavailable", tool="username")
        return AdapterResult(username_findings or [], status="ok", tool="username")

    def unavail(*a, **k):
        return AdapterResult(status="unavailable", tool="x")

    def people(*a, **k):
        if all_unavailable:
            return {"findings": [], "status": "unavailable"}
        return {"findings": [], "status": "blocked"}

    monkeypatch.setattr(sweep.username_mod, "run", uname)
    monkeypatch.setattr(sweep.email_mod, "run", unavail)
    monkeypatch.setattr(sweep.phone_mod, "run", unavail)
    monkeypatch.setattr(sweep.domain_mod, "run", unavail)
    monkeypatch.setattr(sweep.people_mod, "run", people)


def test_integration_fanout(monkeypatch):
    """person_sweep generates candidates, calls adapters, merges results."""
    calls = {"gen": 0}
    real_gen = sweep.candidates_mod.generate_candidates

    def spy_gen(*a, **k):
        calls["gen"] += 1
        return real_gen(*a, **k)

    monkeypatch.setattr(sweep.candidates_mod, "generate_candidates", spy_gen)

    fixture = [Finding(selector="amandab", source_tool="sherlock",
                       value="github.com/amandab", exists=True)]
    _stub(monkeypatch, username_findings=fixture)

    res = sweep.person_sweep("Amanda Bennett", city="Omaha", depth="quick")

    assert calls["gen"] == 1
    assert res["candidates"]  # non-empty
    assert isinstance(res["findings"], list)
    assert any(f.source_tool == "sherlock" for f in res["findings"])
    tools = {s["tool"] for s in res["sources"]}
    assert {"username", "people_search"}.issubset(tools)


def test_all_unavailable_returns_empty_no_raise(monkeypatch):
    """A-3: every adapter unavailable → empty findings, sources unavailable."""
    _stub(monkeypatch, all_unavailable=True)
    res = sweep.person_sweep("Amanda Bennett", depth="quick")
    assert res["findings"] == []
    assert all(s["status"] == "unavailable" for s in res["sources"])


def test_confidence_by_agreement_end_to_end(monkeypatch):
    """Two adapters returning the same value → high confidence via person_sweep."""
    def uname(sel, *a, **k):
        return AdapterResult(
            [Finding(selector=sel, source_tool="sherlock", value="site/x", exists=True)],
            status="ok", tool="username",
        )

    def email_run(*a, **k):
        return AdapterResult(
            [Finding(selector="e", source_tool="holehe", value="site/x", exists=True)],
            status="ok", tool="email",
        )

    def unavail(*a, **k):
        return AdapterResult(status="unavailable", tool="x")

    def people(*a, **k):
        return {"findings": [], "status": "blocked"}

    monkeypatch.setattr(sweep.username_mod, "run", uname)
    monkeypatch.setattr(sweep.email_mod, "run", email_run)
    monkeypatch.setattr(sweep.phone_mod, "run", unavail)
    monkeypatch.setattr(sweep.domain_mod, "run", unavail)
    monkeypatch.setattr(sweep.people_mod, "run", people)

    res = sweep.person_sweep("Amanda Bennett", email="amanda@example.com",
                             depth="quick")
    high = [f for f in res["findings"] if f.value == "site/x"]
    assert high and all(f.confidence == "high" for f in high)
