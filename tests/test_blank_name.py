"""A blank name is refused up front (found driving the real stdio server).

Before: person_sweep("") ran the people_search job, investigate("") also
queried CourtListener, and both returned manual-assist links that search for
an empty string (Google ``"" obituary``, ``truepeoplesearch ...?name=``).
"""

import pytest

import harrier.investigate as inv
import harrier.sweep as sweep
from harrier import assist


@pytest.mark.parametrize("name", ["", "   ", None])
def test_person_sweep_refuses_blank_name(monkeypatch, name):
    def boom(*a, **k):
        raise AssertionError("no job may run for a blank name")

    monkeypatch.setattr(sweep, "run_jobs_sync", boom)
    res = sweep.person_sweep(name)
    assert res["findings"] == [] and res["manual_assist"] == []
    assert res["error"] == "empty name"
    assert res["sources"] == [{"tool": "person_sweep", "status": "error",
                               "count": 0, "reasons": ["empty name"]}]


def test_investigate_refuses_blank_name(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("nothing may be queried for a blank name")

    monkeypatch.setattr(inv.sweep_mod, "person_sweep", boom)
    monkeypatch.setattr(inv.court_mod, "run", boom)
    res = inv.investigate("  ")
    assert res["error"] == "empty name"
    assert res["rounds_run"] == 0 and res["tool_calls"] == []
    assert res["manual_assist"] == []


def test_manual_assist_links_empty_for_blank_name():
    assert assist.manual_assist_links("  ") == []


def test_build_graph_tool_passes_on_the_sweep_error_and_sources():
    # build_graph with no findings runs person_sweep; it used to drop the
    # sweep's error and sources[], so a failed collection looked like an
    # empty graph.
    import asyncio
    import json

    from harrier.server import create_app

    async def go():
        res = await create_app().call_tool("build_graph", {"name": " "})
        content = res[0] if isinstance(res, tuple) else res
        return json.loads(content[0].text)

    out = asyncio.run(go())
    assert out["error"] == "empty name"
    assert out["sources"][0]["reasons"] == ["empty name"]


def test_build_graph_tool_with_findings_has_no_sweep_fields_set():
    import asyncio
    import json

    from harrier.server import create_app

    async def go():
        res = await create_app().call_tool("build_graph", {"name": "Jane Doe", "findings": []})
        content = res[0] if isinstance(res, tuple) else res
        return json.loads(content[0].text)

    out = asyncio.run(go())
    assert out["error"] is None and out["sources"] == []
