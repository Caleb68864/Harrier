"""Domain adapter — theHarvester via subprocess.

theHarvester enumerates emails, subdomains and hosts for a domain from free
sources. It has no stable pip entrypoint on this host, so if the `theHarvester`
binary is absent the adapter degrades to ``status="unavailable"``. It never
raises into the sweep.

Invocation: ``theHarvester -d <domain> -b all -f <tmp.json>`` then parse the
JSON report (``-f`` writes ``<name>.json``).
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile

from harrier.adapters import (
    AdapterResult,
    SelectorError,
    binary_available,
    run_subprocess,
    validate_selector,
)
from harrier.schema import Finding

TOOL = "domain"
HARVESTER_BIN = "theHarvester"


def _validate_domain(selector: str) -> str:
    s = validate_selector(selector)  # rejects shell metacharacters
    if "." not in s:
        raise SelectorError(f"not a valid domain: {selector!r}")
    return s.lower()


def run(selector: str, timeout: int = 30, sources: str = "all", **opts) -> AdapterResult:
    """Harvest a domain with theHarvester if available."""
    try:
        domain = _validate_domain(selector)
    except SelectorError as exc:
        return AdapterResult(status="error", tool=TOOL, reason=str(exc))

    if not binary_available(HARVESTER_BIN):
        return AdapterResult(
            status="unavailable",
            tool=TOOL,
            reason="theHarvester binary not found; install it to enable "
            "domain harvesting",
        )

    with tempfile.TemporaryDirectory(prefix="harrier_harvester_") as tmp:
        out_base = os.path.join(tmp, "report")
        args = [HARVESTER_BIN, "-d", domain, "-b", sources, "-f", out_base]
        try:
            run_subprocess(args, timeout=timeout)
        except subprocess.TimeoutExpired:
            return AdapterResult(status="unavailable", tool=TOOL,
                                 reason="theHarvester timed out")
        except (FileNotFoundError, OSError):
            return AdapterResult(status="unavailable", tool=TOOL,
                                 reason="theHarvester not runnable")
        findings = _parse_report(tmp, domain)
    return AdapterResult(findings, status="ok", tool=TOOL)


def _parse_report(folder: str, domain: str) -> list[Finding]:
    """Parse theHarvester's JSON report from `folder`."""
    findings: list[Finding] = []
    report_path = None
    for name in os.listdir(folder):
        if name.endswith(".json"):
            report_path = os.path.join(folder, name)
            break
    if not report_path:
        return findings
    try:
        with open(report_path, encoding="utf-8", errors="replace") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return findings

    for email in (data.get("emails") or []):
        findings.append(
            Finding(selector=domain, source_tool="theHarvester", value=email,
                    exists=True, confidence="low", tier="free",
                    raw={"type": "email", "value": email})
        )
    for host in (data.get("hosts") or []):
        findings.append(
            Finding(selector=domain, source_tool="theHarvester", value=host,
                    exists=True, confidence="low", tier="free",
                    raw={"type": "host", "value": host})
        )
    return findings


def register(app) -> None:
    """Register the `domain_harvest` MCP tool."""

    @app.tool(name="domain_harvest")
    def domain_harvest(selector: str, timeout: int = 30) -> dict:
        """Harvest emails/hosts for a domain via theHarvester (free sources)."""
        res = run(selector, timeout=timeout)
        return {
            "status": res.status,
            "count": len(res),
            "findings": [f.model_dump() for f in res],
            "reason": res.reason,
        }
