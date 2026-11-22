"""Defects found in the 2026-11-21 bug hunt (roadmap C40-C44).

Findings here come from the real adapters (with their tool calls faked), not
hand-built, so the graph and investigate are tested on what they actually get.
"""

from types import SimpleNamespace

import harrier.investigate as inv
from harrier.adapters import AdapterResult, court, people_search, phone
from harrier.graph import build_graph, to_graphml
from harrier.schema import Finding

_PHONE_OUT = (
    "Running scan for phone number +14025551234...\n\n"
    "Results for local\nRaw local: 4025551234\nE164: +14025551234\nCountry: US\n\n"
    "Results for numverify\nValid: true\nCarrier: Example Wireless\n\n"
    "2 scanner(s) succeeded\n"
)


def _phone_findings(monkeypatch):
    monkeypatch.setattr(phone, "binary_available", lambda n: True)
    monkeypatch.setattr(phone, "run_subprocess", lambda args, timeout=30:
                        SimpleNamespace(returncode=0, stdout=_PHONE_OUT, stderr=""))
    return list(phone.run("+1 402 555 1234"))


# --- C40: graph placed the phone's country/carrier as the phone ---------------

def test_graph_phone_node_is_the_number(monkeypatch):
    g = build_graph(_phone_findings(monkeypatch), {"name": "Amanda Bennett"})
    phones = [n for n in g["nodes"] if n["type"] == "phone"]
    # One phone, labelled with the number; not "US" and "Example Wireless".
    assert [n["label"] for n in phones] == ["+14025551234"]
    edges = [e for e in g["edges"] if e["relation"] == "has_phone"]
    assert len(edges) == 1


# --- C41: graph placed a blocked people_search manual step as a lead ----------

def test_graph_skips_blocked_people_search_finding():
    res = people_search.run("Amanda Bennett", consent=False)
    assert res["findings"][0].url  # the real blocked finding carries a site URL
    g = build_graph(res["findings"], {"name": "Amanda Bennett"})
    assert [n["type"] for n in g["nodes"]] == ["person"]
    assert g["edges"] == []


# --- C42: graph linked profiles that verify proved dead -----------------------

def test_graph_skips_findings_verify_marked_absent():
    dead = Finding(selector="awademan", source_tool="sherlock",
                   url="https://github.com/awademan", value="https://github.com/awademan",
                   exists=False, reason="verify: HTTP 404 — profile not found",
                   raw={"verify": {"verdict": "false_positive"}})
    live = Finding(selector="awademan", source_tool="sherlock",
                   url="https://gitlab.com/awademan", value="https://gitlab.com/awademan",
                   exists=True)
    g = build_graph([dead, live], {"name": "Amanda Bennett"})
    labels = {n["label"] for n in g["nodes"]}
    assert "https://gitlab.com/awademan" in labels
    assert "https://github.com/awademan" not in labels
    assert "github.com/awademan" not in to_graphml(g)


# --- C43: CourtListener now refuses anonymous API calls -----------------------

def test_court_401_without_token_says_a_token_is_required(monkeypatch):
    # Checked 2026-11-21: v4 search answers 401 "Authentication credentials
    # were not provided." to an anonymous call (v3: 403).
    monkeypatch.delenv("COURTLISTENER_TOKEN", raising=False)
    monkeypatch.setattr(court, "_fetch", lambda q, t: (401, None))
    res = court.run("Amanda Bennett")
    assert res.status == "unavailable"
    assert "requires an API token" in res.reason
    assert "COURTLISTENER_TOKEN" in res.reason


def test_court_401_with_token_says_check_it(monkeypatch):
    monkeypatch.setenv("COURTLISTENER_TOKEN", "x")
    monkeypatch.setattr(court, "_fetch", lambda q, t: (401, None))
    res = court.run("Amanda Bennett")
    assert "check COURTLISTENER_TOKEN" in res.reason


# --- C44: investigate dropped every source status, and re-ran the court call ---

def _corroborated_sweep(*a, **k):
    f = Finding(selector="awademan", source_tool="maigret", url="https://x/awademan",
                value="x", exists=True, confidence="high",
                raw={"ids": {"fullname": "Amanda Kowalski"},
                     "verify": {"verdict": "corroborated"}})
    return {"findings": [f], "candidates": [], "suppressed": 0, "verify": None,
            "manual_assist": [],
            "sources": [{"tool": "phone", "status": "unavailable", "count": 0,
                         "reasons": ["phoneinfoga binary not found"]}]}


def test_investigate_reports_sources_and_queries_court_once(monkeypatch):
    calls = []

    def fake_court(name):
        calls.append(name)
        return AdapterResult(status="unavailable", tool="courtlistener",
                             reason="CourtListener unreachable (HTTP 401)")

    monkeypatch.setattr(inv.sweep_mod, "person_sweep", _corroborated_sweep)
    monkeypatch.setattr(inv.court_mod, "run", fake_court)
    res = inv.investigate("Amanda Bennett", maiden="Wademan", max_rounds=2)
    assert res["rounds_run"] == 2
    assert calls == ["Amanda Bennett"]  # same name every round: ask once
    by_tool = {s["tool"]: s for s in res["sources"]}
    assert by_tool["courtlistener"]["status"] == "unavailable"
    assert "HTTP 401" in by_tool["courtlistener"]["reasons"][0]
    assert by_tool["phone"]["status"] == "unavailable"


def test_investigate_tool_payload_has_sources(monkeypatch):
    import asyncio
    import json

    from harrier.server import create_app

    monkeypatch.setattr(inv.sweep_mod, "person_sweep", _corroborated_sweep)
    monkeypatch.setattr(inv.court_mod, "run", lambda name: AdapterResult(
        status="empty", tool="courtlistener"))

    async def go():
        res = await create_app().call_tool(
            "investigate", {"name": "Amanda Bennett", "max_rounds": 1})
        content = res[0] if isinstance(res, tuple) else res
        return json.loads(content[0].text)

    out = asyncio.run(go())
    assert {s["tool"] for s in out["sources"]} == {"phone", "courtlistener"}
