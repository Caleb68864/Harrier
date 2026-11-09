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
    exit_failure_reason,
    run_subprocess,
    validate_selector,
)
from harrier.schema import Finding

TOOL = "domain"
HARVESTER_BIN = "theHarvester"

# Free, keyless passive sources only (legal constraint: free public sources).
# ``-b all`` would include API-key / paid-tier modules (shodan, hunter, censys,
# securitytrails, ...) and search-engine scrapers; pin an explicit allowlist so
# the constraint holds by construction. Certificate-transparency + passive-DNS
# sources that answer without a key. Re-check against the installed version.
FREE_SOURCES = (
    "anubis", "certspotter", "crtsh", "hackertarget", "otx", "rapiddns",
    "threatminer", "urlscan",
)


def _validate_sources(sources) -> str:
    """Return a comma-joined subset of FREE_SOURCES, or raise SelectorError.

    ``None`` means the full free allowlist. Anything outside it (including
    ``"all"``) is refused rather than silently widened.
    """
    if sources is None:
        return ",".join(FREE_SOURCES)
    if isinstance(sources, str):
        items = [s.strip().lower() for s in sources.split(",") if s.strip()]
    else:
        items = [str(s).strip().lower() for s in sources if str(s).strip()]
    bad = [s for s in items if s not in FREE_SOURCES]
    if bad or not items:
        raise SelectorError(
            f"theHarvester sources not allowed: {bad or sources!r}; "
            f"use a subset of the free keyless list: {', '.join(FREE_SOURCES)}")
    return ",".join(dict.fromkeys(items))


def _validate_domain(selector: str) -> str:
    s = validate_selector(selector)  # rejects shell metacharacters
    if "." not in s:
        raise SelectorError(f"not a valid domain: {selector!r}")
    return s.lower()


def run(selector: str, timeout: int = 30, sources=None, **opts) -> AdapterResult:
    """Harvest a domain with theHarvester (free keyless sources only)."""
    try:
        domain = _validate_domain(selector)
        source_arg = _validate_sources(sources)
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
        args = [HARVESTER_BIN, "-d", domain, "-b", source_arg, "-f", out_base]
        try:
            proc = run_subprocess(args, timeout=timeout)
        except subprocess.TimeoutExpired:
            return AdapterResult(status="unavailable", tool=TOOL,
                                 reason="theHarvester timed out")
        except (FileNotFoundError, OSError):
            return AdapterResult(status="unavailable", tool=TOOL,
                                 reason="theHarvester not runnable")
        findings = _parse_report(tmp, domain)
    failure = exit_failure_reason("theHarvester", proc)
    if failure and not findings:  # partial report on non-zero exit still counts
        return AdapterResult(status="error", tool=TOOL, reason=failure)
    return AdapterResult(findings, status="ok", tool=TOOL, reason=failure)


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

    if not isinstance(data, dict):  # drifted/malformed report shape
        return findings

    for kind, key in (("email", "emails"), ("host", "hosts")):
        items = data.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            # Emails/hosts are strings by definition; a number/dict is junk.
            value = item.strip() if isinstance(item, str) else ""
            if not value:
                continue
            findings.append(
                Finding(selector=domain, source_tool="theHarvester", value=value,
                        exists=True, confidence="low", tier="free",
                        raw={"type": kind, "value": value})
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
