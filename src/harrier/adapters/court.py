"""Court-records adapter — CourtListener / RECAP (roadmap Phase 4b).

CourtListener exposes a free REST search API over millions of federal dockets
and opinions. Anonymous access works (rate-limited); an optional token in
``COURTLISTENER_TOKEN`` raises the limit. Divorce / name-change dockets are a
maiden-name lead. Structured and un-walled — no anti-bot fight.

Degrades honestly: any network/parse failure → ``status="unavailable"`` with a
pointer to the manual-assist CourtListener link. Never raises.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlencode

from harrier.adapters import AdapterResult
from harrier.schema import Finding

TOOL = "courtlistener"
_API = "https://www.courtlistener.com/api/rest/v4/search/"
_UA = "harrier-osint/0.1 (+https://github.com/; research use)"


def _fetch(query: str, timeout: int) -> tuple[int, dict | None]:
    """Query the CourtListener search API. Returns (status, json|None)."""
    url = _API + "?" + urlencode({"q": query, "type": "r"})
    req = urllib.request.Request(url, headers={"User-Agent": _UA,
                                               "Accept": "application/json"})
    token = os.environ.get("COURTLISTENER_TOKEN")
    if token:
        req.add_header("Authorization", f"Token {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return getattr(resp, "status", 200) or 200, json.load(resp)
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception:  # noqa: BLE001 — any failure degrades to unavailable
        return 0, None


def run(name: str, state: str | None = None, timeout: int = 15) -> AdapterResult:
    """Search CourtListener for a person by name. Never raises."""
    name = (name or "").strip()
    if not name:
        return AdapterResult(status="error", tool=TOOL, reason="empty name")
    # Name is URL-encoded into an API query (no subprocess/shell), so a plain
    # emptiness check is the right guard — apostrophes/hyphens in names are fine.

    status, data = _fetch(f'"{name}"', timeout)
    if data is None:
        return AdapterResult(
            status="unavailable", tool=TOOL,
            reason=f"CourtListener unreachable (HTTP {status}); use the manual_assist "
                   "CourtListener link.",
        )

    results = data.get("results") or []
    findings: list[Finding] = []
    for r in results[:20]:
        caption = r.get("caseName") or r.get("case_name") or "case"
        court = r.get("court") or r.get("court_id") or ""
        date = r.get("dateFiled") or r.get("date_filed") or ""
        rel = r.get("absolute_url") or ""
        url = ("https://www.courtlistener.com" + rel) if rel.startswith("/") else (rel or None)
        findings.append(Finding(
            selector=name, source_tool=TOOL, url=url, value=caption, exists=True,
            confidence="low", tier="free",
            reason=" · ".join(x for x in (str(court), str(date)) if x) or None,
            raw={"docket_number": r.get("docketNumber") or r.get("docket_number")},
        ))
    return AdapterResult(findings, status="ok" if findings else "empty", tool=TOOL)


def register(app) -> None:
    """Register the `court_search` MCP tool."""

    @app.tool(name="court_search")
    def court_search(name: str, state: str | None = None) -> dict:
        """Search CourtListener/RECAP federal court records for a person by name."""
        res = run(name, state=state)
        return {
            "status": res.status,
            "count": len(res),
            "findings": [f.model_dump() for f in res],
            "reason": res.reason,
        }
