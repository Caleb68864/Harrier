"""Domain adapter — theHarvester via subprocess.

theHarvester enumerates emails, subdomains and hosts for a domain from free
sources. It has no stable pip entrypoint on this host, so if the `theHarvester`
binary is absent the adapter degrades to ``status="unavailable"``. It never
raises into the sweep.

Invocation: ``theHarvester -d <domain> -b <FREE_SOURCES> -f <tmp.json>`` then
parse the JSON report (``-f`` writes ``<name>.json``). Never ``-b all``.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile

from harrier.adapters import (
    log_outcome,
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
# sources that answer without a key.
#
# Checked against theHarvester 4.11.1 (GitHub release, 2026-06-03; the PyPI
# "theHarvester" package is a stale 0.0.1 from 2019): every name below is in
# ``Core.get_supportedengines()`` and needs no API key (hackertarget takes an
# optional key but works without one). ``anubis`` and ``threatminer`` were
# dropped: 4.11.1 has no such modules, and theHarvester rejects the whole
# ``-b`` list ("Invalid source", exit 1) if any one name is unknown. Names are
# matched case-sensitively. Re-check when moving to another version.
#
# Second pass (4.11.1 source, ``theHarvester/discovery/*.py`` and the
# dispatch in ``__main__.py``). Each module below reads no key (none appears
# in ``api-keys.yaml`` or calls ``Core.*_key()``) and only queries a
# third-party dataset; nothing is sent to the target's own hosts:
#   commoncrawl      added: index.commoncrawl.org CDX (3 fixed 2023-24
#                    indexes) -> hostnames seen in crawled URLs
#   robtex           added: freeapi.robtex.com passive DNS forward/reverse
#                    -> hostnames (rrname, CNAME targets) and A-record IPs
#   subdomaincenter  added: api.subdomain.center -> list of subdomains
#   thc              added: ip.thc.org subdomain download -> hostnames
#   threatcrowd      EXCLUDED (owner, 2026-11-16): keyless and passive, but
#                    4.11.1 calls it over plain http (ci-www.threatcrowd.org),
#                    so the target domain would cross the network
#                    unencrypted; the service may also no longer be running.
#   waybackarchive   added: web.archive.org CDX -> hostnames seen in
#                    archived URLs
#   shodanInternetDB EXCLUDED: keyless, but it first resolves the target
#                    with ``socket.getaddrinfo`` (a live DNS lookup that
#                    reaches the target's nameservers) before asking
#                    internetdb.shodan.io about each IP. Not a pure
#                    third-party lookup. Also mixed-case, which
#                    ``_validate_sources`` (lowercases input) can't match.
HARVESTER_VERSION_CHECKED = "4.11.1"
# One theHarvester run queries every source above; a timeout returns nothing
# at all, so the budget must cover the slowest (thc can wait 60 s and retry).
HARVEST_TIMEOUT = 120
FREE_SOURCES = (
    "certspotter", "commoncrawl", "crtsh", "hackertarget", "otx",
    "rapiddns", "robtex", "subdomaincenter", "thc", "urlscan",
    "waybackarchive",
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


@log_outcome
def run(selector: str, timeout: int = HARVEST_TIMEOUT, sources=None, **opts) -> AdapterResult:
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
    def domain_harvest(selector: str, timeout: int = HARVEST_TIMEOUT) -> dict:
        """Harvest emails/hosts for a domain via theHarvester (free sources)."""
        res = run(selector, timeout=timeout)
        return {
            "status": res.status,
            "count": len(res),
            "findings": [f.model_dump() for f in res],
            "reason": res.reason,
        }
