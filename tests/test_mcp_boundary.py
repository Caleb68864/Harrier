"""MCP-boundary tests: call registered tools through create_app() and check the
payload contract (status/count/findings/reason) the calling agent relies on.
Only network-free paths are exercised."""

import asyncio
import json

from harrier.server import create_app

EXPECTED_TOOLS = {
    "build_graph", "court_search", "domain_harvest", "email_recon",
    "genealogy_search", "generate_candidates", "investigate", "manual_assist",
    "people_search", "person_sweep", "phone_lookup", "username_sweep",
}


def _call(name, args):
    app = create_app()

    async def go():
        res = await app.call_tool(name, args)
        content = res[0] if isinstance(res, tuple) else res
        return json.loads(content[0].text) if content else None

    return asyncio.run(go())


def test_all_tools_registered():
    app = create_app()
    names = {t.name for t in asyncio.run(app.list_tools())}
    assert EXPECTED_TOOLS <= names


def test_adapter_tools_return_reason_on_bad_input():
    for tool, args in (("phone_lookup", {"selector": "abc"}),
                       ("domain_harvest", {"selector": "--filename=x.json"}),
                       ("username_sweep", {"selector": "a;b"}),
                       ("email_recon", {"selector": "not-an-email"})):
        out = _call(tool, args)
        assert out["status"] == "error", tool
        assert out["count"] == 0 and out["findings"] == []
        assert out["reason"], tool


def test_people_search_consent_gate_payload():
    out = _call("people_search", {"name": "Amanda Bennett"})
    assert out["status"] == "blocked"
    assert "consent=False" in out["reason"]
    assert out["findings"][0]["tier"] == "blocked"


def test_build_graph_reports_invalid_findings():
    good = {"selector": "amandab", "source_tool": "sherlock",
            "url": "https://github.com/amandab", "value": "https://github.com/amandab"}
    out = _call("build_graph", {"name": "Amanda Bennett", "findings": [good, {"x": 1}]})
    assert out["stats"]["edges"] == 1
    assert out["invalid_findings"] and out["invalid_findings"][0]["index"] == 1
    assert out["graphml"].startswith("<?xml")


def test_manual_assist_payload():
    out = _call("manual_assist", {"name": "Amanda Bennett"})
    assert out["count"] == len(out["links"]) > 0
