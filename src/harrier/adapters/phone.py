"""Phone adapter — PhoneInfoga (Go binary) via subprocess.

PhoneInfoga is a Go program; if Go isn't installed and the `phoneinfoga` binary
isn't on PATH, this adapter degrades to ``status="unavailable"`` (its common
state on this host — Go is absent). It never raises into the sweep.

PhoneInfoga scan: ``phoneinfoga scan -n <number>``. Checked against the
PhoneInfoga source at v2.11.0 (the latest release, 2024-02-21): ``scan`` has no
output-format flag (the ``-o/--output`` flag is commented out in
``cmd/scan.go``) and always writes ``output.Console``, the only output kind in
``lib/output``. JSON exists only through ``phoneinfoga serve`` (REST API). So
we parse the console format::

    Running scan for phone number +1...
    Results for <scanner>
    <Field>: <value>
    <Struct field>:
    \t<Nested field>: <value>

    The following scanners returned errors:
    <scanner>: <error>

    N scanner(s) succeeded
"""

from __future__ import annotations

import re
import subprocess

from harrier.adapters import (
    log_outcome,
    AdapterResult,
    SelectorError,
    as_text,
    binary_available,
    exit_failure_reason,
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


@log_outcome
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

    failure = exit_failure_reason("phoneinfoga", proc)
    if failure:  # stdout of a failed scan is an error message, not a result
        return AdapterResult(status="error", tool=TOOL, reason=failure)

    findings = _parse(proc.stdout, number)
    _, scan_errors = _parse_console(proc.stdout)
    reason = "; ".join(f"{k}: {v}" for k, v in sorted(scan_errors.items())) or None
    if reason:
        reason = f"phoneinfoga scanner errors: {reason}"
    if not findings:
        return AdapterResult(status="error" if scan_errors else "empty", tool=TOOL,
                             reason=reason or "phoneinfoga returned no scanner results")
    return AdapterResult(findings, status="ok", tool=TOOL, reason=reason)


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_RESULTS_RE = re.compile(r"^Results for (.+)$")
_SUCCEEDED_RE = re.compile(r"^\d+ scanner\(s\) succeeded$")
_ERRORS_HEADER = "The following scanners returned errors:"
# Fields worth showing as the finding's value, most specific first.
_VALUE_FIELDS = ("Carrier", "Line type", "Location", "Country name", "Country")


def _parse_console(stdout: str) -> tuple[dict[str, dict], dict[str, str]]:
    """Parse ``phoneinfoga scan`` console output.

    Returns ``({scanner: {field: value | [values]}}, {scanner: error})``.
    Nested struct fields are flattened (``Response > Format > Number Format``
    becomes ``Number Format``); a field seen twice becomes a list (the
    googlesearch scanner prints one ``URL:`` per search link).
    """
    results: dict[str, dict] = {}
    errors: dict[str, str] = {}
    section: dict | None = None
    in_errors = False
    for line in _ANSI_RE.sub("", stdout or "").splitlines():
        text = line.strip()
        if not text or _SUCCEEDED_RE.match(text) or text.startswith("Running scan for"):
            continue
        m = _RESULTS_RE.match(text)
        if m:
            section = results.setdefault(m.group(1).strip(), {})
            in_errors = False
            continue
        if text == _ERRORS_HEADER:
            section, in_errors = None, True
            continue
        key, sep, value = text.partition(": ")
        if not sep:  # "Field:" header of a nested struct/list, or noise
            continue
        if in_errors:
            errors[key.strip()] = value.strip()
        elif section is not None:
            key, value = key.strip(), value.strip()
            if key in section:
                prev = section[key]
                section[key] = (prev if isinstance(prev, list) else [prev]) + [value]
            else:
                section[key] = value
    return results, errors


def _parse(stdout: str, number: str) -> list[Finding]:
    """One Finding per PhoneInfoga scanner that returned a result."""
    results, _ = _parse_console(stdout)
    findings: list[Finding] = []
    for scanner, fields in results.items():
        value = next((as_text(fields[k]) for k in _VALUE_FIELDS
                      if isinstance(fields.get(k), str) and fields[k]), None)
        findings.append(
            Finding(
                selector=number,
                source_tool="phoneinfoga",
                value=value or f"{scanner} scan",
                exists=None,
                confidence="low",
                tier="free",
                reason=f"phoneinfoga scanner: {scanner}",
                raw={"scanner": scanner, "fields": fields},
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
