"""Username adapter — Sherlock (primary) with Maigret fallback.

Both are invoked via subprocess (list args, no shell). Neither prints clean
JSON to stdout, so:
  * Sherlock: ``--folderoutput <tmp> --print-found --timeout 30`` writes
    ``<username>.txt`` (one found URL per line); we parse that file.
  * Maigret: ``--json simple`` writes a JSON file to the output folder.

Missing binary / crash / bad selector → ``status="unavailable"`` (or
``"error"``), empty findings, no exception.
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

TOOL = "username"
SHERLOCK_BIN = "sherlock"
MAIGRET_BIN = "maigret"


def _parse_sherlock_file(path: str, selector: str) -> list[Finding]:
    """Parse a Sherlock per-run result file (one found profile URL per line)."""
    findings: list[Finding] = []
    if not os.path.exists(path):
        return findings
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            url = line.strip()
            if not url or not url.lower().startswith("http"):
                continue
            findings.append(
                Finding(
                    selector=selector,
                    source_tool="sherlock",
                    url=url,
                    value=url,
                    exists=True,
                    confidence="low",  # single-source until correlated
                    tier="free",
                    raw={"line": url},
                )
            )
    return findings


def _run_sherlock(selector: str, timeout: int) -> AdapterResult | None:
    """Run Sherlock; return an AdapterResult, or None if the binary is absent."""
    if not binary_available(SHERLOCK_BIN):
        return None
    with tempfile.TemporaryDirectory(prefix="harrier_sherlock_") as tmp:
        args = [
            SHERLOCK_BIN,
            selector,
            "--folderoutput",
            tmp,
            "--print-found",
            "--timeout",
            str(timeout),
        ]
        try:
            run_subprocess(args, timeout=timeout + 5)
        except subprocess.TimeoutExpired:
            return AdapterResult(status="unavailable", tool="sherlock",
                                 reason="sherlock timed out")
        except (FileNotFoundError, OSError):
            return None
        result_file = os.path.join(tmp, f"{selector}.txt")
        findings = _parse_sherlock_file(result_file, selector)
    return AdapterResult(findings, status="ok", tool="sherlock")


def _parse_maigret_json(path: str, selector: str) -> list[Finding]:
    findings: list[Finding] = []
    if not os.path.exists(path):
        return findings
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return findings
    # maigret simple json: {site: {status: {status: "Claimed"}, url_user: ...}}
    for site, info in (data or {}).items():
        if not isinstance(info, dict):
            continue
        status = info.get("status", {})
        claimed = isinstance(status, dict) and status.get("status") == "Claimed"
        if not claimed:
            continue
        url = info.get("url_user") or info.get("url")
        findings.append(
            Finding(
                selector=selector,
                source_tool="maigret",
                url=url,
                value=url or site,
                exists=True,
                confidence="low",
                tier="free",
                raw={"site": site},
            )
        )
    return findings


def _run_maigret(selector: str, timeout: int) -> AdapterResult | None:
    if not binary_available(MAIGRET_BIN):
        return None
    with tempfile.TemporaryDirectory(prefix="harrier_maigret_") as tmp:
        args = [MAIGRET_BIN, selector, "--json", "simple", "--folderoutput", tmp,
                "--timeout", str(timeout)]
        try:
            run_subprocess(args, timeout=timeout + 5)
        except subprocess.TimeoutExpired:
            return AdapterResult(status="unavailable", tool="maigret",
                                 reason="maigret timed out")
        except (FileNotFoundError, OSError):
            return None
        # maigret names the file report_<username>_simple.json
        candidate = os.path.join(tmp, f"report_{selector}_simple.json")
        findings = _parse_maigret_json(candidate, selector)
        if not findings:
            # fall back to any *.json in the folder
            for name in os.listdir(tmp):
                if name.endswith(".json"):
                    findings = _parse_maigret_json(os.path.join(tmp, name), selector)
                    if findings:
                        break
    return AdapterResult(findings, status="ok", tool="maigret")


def run(selector: str, timeout: int = 30, **opts) -> AdapterResult:
    """Sweep a username across site-enumeration tools.

    Tries Sherlock first, then Maigret. If neither binary is installed, returns
    ``status="unavailable"`` with no findings.
    """
    try:
        selector = validate_selector(selector)
    except SelectorError as exc:
        return AdapterResult(status="error", tool=TOOL, reason=str(exc))

    result = _run_sherlock(selector, timeout)
    if result is None:
        result = _run_maigret(selector, timeout)
    if result is None:
        return AdapterResult(
            status="unavailable",
            tool=TOOL,
            reason="no username tool available (install sherlock or maigret)",
        )
    return result


def register(app) -> None:
    """Register the `username_sweep` MCP tool."""

    @app.tool(name="username_sweep")
    def username_sweep(selector: str, timeout: int = 30) -> dict:
        """Enumerate a username across social sites via Sherlock/Maigret."""
        res = run(selector, timeout=timeout)
        return {
            "status": res.status,
            "count": len(res),
            "findings": [f.model_dump() for f in res],
            "reason": res.reason,
        }
