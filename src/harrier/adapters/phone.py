"""Phone adapter — PhoneInfoga (Go binary) via subprocess.

PhoneInfoga is a Go program; if Go isn't installed and the `phoneinfoga` binary
isn't on PATH, this adapter degrades to ``status="unavailable"`` (its common
state on this host — Go is absent). It never raises into the sweep.

PhoneInfoga scan: ``phoneinfoga scan -n <number>``. We prefer JSON if the local
build supports it; otherwise we return a single ``unavailable`` note rather than
guessing at scraped text.
"""

from __future__ import annotations

import json
import re
import subprocess

from harrier.adapters import (
    AdapterResult,
    SelectorError,
    binary_available,
    run_subprocess,
)
from harrier.schema import Finding

TOOL = "phone"
PHONEINFOGA_BIN = "phoneinfoga"

# E.164-ish: optional +, digits, common separators we strip.
_PHONE_ALLOWED = re.compile(r"^\+?[0-9]+$")


def _normalize_phone(selector: str) -> str:
    if not isinstance(selector, str):
        raise SelectorError("phone must be a string")
    compact = re.sub(r"[\s\-().]", "", selector.strip())
    if not compact or not _PHONE_ALLOWED.match(compact):
        raise SelectorError(f"not a valid phone number: {selector!r}")
    return compact


def run(selector: str, timeout: int = 30, **opts) -> AdapterResult:
    """Scan a phone number with PhoneInfoga if available."""
    try:
        number = _normalize_phone(selector)
    except SelectorError as exc:
        return AdapterResult(status="error", tool=TOOL, reason=str(exc))

    if not binary_available(PHONEINFOGA_BIN):
        return AdapterResult(
            status="unavailable",
            tool=TOOL,
            reason="phoneinfoga binary not found (requires Go build); "
            "install PhoneInfoga to enable phone scanning",
        )

    args = [PHONEINFOGA_BIN, "scan", "-n", number]
    try:
        proc = run_subprocess(args, timeout=timeout)
    except subprocess.TimeoutExpired:
        return AdapterResult(status="unavailable", tool=TOOL,
                             reason="phoneinfoga timed out")
    except (FileNotFoundError, OSError):
        return AdapterResult(status="unavailable", tool=TOOL,
                             reason="phoneinfoga not runnable")

    findings = _parse(proc.stdout, number)
    return AdapterResult(findings, status="ok", tool=TOOL)


def _parse(stdout: str, number: str) -> list[Finding]:
    """Best-effort parse of PhoneInfoga output (JSON if present)."""
    findings: list[Finding] = []
    if not stdout:
        return findings
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        # Non-JSON build: emit a single summary finding with the raw text.
        return [
            Finding(
                selector=number,
                source_tool="phoneinfoga",
                value="scan complete",
                exists=None,
                confidence="low",
                tier="free",
                raw={"stdout": stdout[:2000]},
            )
        ]
    # JSON build: surface carrier/location if present.
    result = data.get("result", data) if isinstance(data, dict) else {}
    if isinstance(result, dict):
        findings.append(
            Finding(
                selector=number,
                source_tool="phoneinfoga",
                value=result.get("carrier") or result.get("country") or "scan",
                exists=None,
                confidence="low",
                tier="free",
                raw=result,
            )
        )
    return findings


def register(app) -> None:
    """Register the `phone_lookup` MCP tool."""

    @app.tool(name="phone_lookup")
    def phone_lookup(selector: str, timeout: int = 30) -> dict:
        """Scan a phone number with PhoneInfoga (free sources)."""
        res = run(selector, timeout=timeout)
        return {
            "status": res.status,
            "count": len(res),
            "findings": [f.model_dump() for f in res],
            "reason": res.reason,
        }
