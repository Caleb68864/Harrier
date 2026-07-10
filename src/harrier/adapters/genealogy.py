"""Genealogy adapter — FamilySearch records (roadmap Phase 4b).

FamilySearch's API is free (nonprofit) but requires an OAuth access token
(register a free developer app + user auth). Without a token this adapter
degrades HONESTLY to ``status="unavailable"`` and points at the manual-assist
FamilySearch link — which needs no token, the analyst just signs in. With a token
in ``FAMILYSEARCH_ACCESS_TOKEN`` it queries the record-search API.

FamilySearch is the #1 free maiden-name resolver: marriage/death records tie a
married name → maiden name → family network.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlencode

from harrier.adapters import AdapterResult
from harrier.schema import Finding

TOOL = "familysearch"
_API = "https://api.familysearch.org/platform/tree/search"
_UA = "harrier-osint/0.1 (research use)"


def _manual_pointer() -> str:
    return ("FamilySearch needs an OAuth access token (set FAMILYSEARCH_ACCESS_TOKEN "
            "after registering a free app). Meanwhile use the manual_assist "
            "FamilySearch link — free, just sign in.")


def run(first: str, last: str, maiden: str | None = None,
        married: str | None = None, timeout: int = 15) -> AdapterResult:
    """Search FamilySearch records. Degrades to unavailable without a token. Never raises."""
    token = os.environ.get("FAMILYSEARCH_ACCESS_TOKEN")
    if not token:
        return AdapterResult(status="unavailable", tool=TOOL, reason=_manual_pointer())

    given = (first or "").strip()
    surname = (maiden or last or "").strip()
    if not given and not surname:
        return AdapterResult(status="error", tool=TOOL, reason="need a name")

    params = {"q.givenName": given, "q.surname": surname}
    if married and married != surname:
        params["q.spouseSurname"] = married
    req = urllib.request.Request(
        _API + "?" + urlencode(params),
        headers={"User-Agent": _UA, "Accept": "application/json",
                 "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        return AdapterResult(status="unavailable", tool=TOOL,
                             reason=f"FamilySearch HTTP {exc.code}; use the manual_assist link.")
    except Exception:  # noqa: BLE001
        return AdapterResult(status="unavailable", tool=TOOL,
                             reason="FamilySearch unreachable; use the manual_assist link.")

    findings: list[Finding] = []
    for e in (data.get("entries") or [])[:20]:
        gedcomx = (e.get("content") or {}).get("gedcomx") or {}
        persons = gedcomx.get("persons") or []
        label = None
        if persons:
            names = persons[0].get("names") or []
            if names:
                forms = names[0].get("nameForms") or [{}]
                label = forms[0].get("fullText")
        findings.append(Finding(
            selector=f"{given} {surname}".strip(), source_tool=TOOL, url=None,
            value=label or "record", exists=True, confidence="low", tier="free",
            raw={"id": e.get("id")}))
    return AdapterResult(findings, status="ok" if findings else "empty", tool=TOOL)


def register(app) -> None:
    """Register the `genealogy_search` MCP tool."""

    @app.tool(name="genealogy_search")
    def genealogy_search(first: str, last: str, maiden: str | None = None,
                         married: str | None = None) -> dict:
        """Search FamilySearch records (maiden-name resolver; needs FAMILYSEARCH_ACCESS_TOKEN)."""
        res = run(first, last, maiden=maiden, married=married)
        return {"status": res.status, "count": len(res),
                "findings": [f.model_dump() for f in res], "reason": res.reason}
