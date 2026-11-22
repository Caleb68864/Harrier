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
    <Header>:
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
# The release the console parser was run against (a real ``scan``, see
# tests/test_phoneinfoga_real.py). Re-check the parser before changing it.
PHONEINFOGA_VERSION_CHECKED = "2.11.0"

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

    Returns ``({scanner: fields}, {scanner: error})``. A top-level field is
    ``value``, or a list if the scanner printed it more than once. A
    ``Header:`` line opens a nested block, indented one tab per level
    (``lib/output/console.go``); its fields are kept under the header, and a
    nested value is always a list, because a slice is printed one element
    at a time and a one-element slice looks like a single field. So the
    googlesearch scanner gives ``{"Social media": {"URL": [...]},
    "Reputation": {"URL": [...]}, ...}`` (checked against a real v2.11.0
    run). A header with nothing under it is left out.
    """
    results: dict[str, dict] = {}
    errors: dict[str, str] = {}
    section: dict | None = None
    headers: list[str] = []  # open "Header:" names, one per indent level
    in_errors = False
    for line in _ANSI_RE.sub("", stdout or "").splitlines():
        text = line.strip()
        if not text or _SUCCEEDED_RE.match(text) or text.startswith("Running scan for"):
            continue
        m = _RESULTS_RE.match(text)
        if m:
            section = results.setdefault(m.group(1).strip(), {})
            headers, in_errors = [], False
            continue
        if text == _ERRORS_HEADER:
            section, headers, in_errors = None, [], True
            continue
        depth = len(line) - len(line.lstrip("\t"))
        del headers[depth:]  # a shallower line closes deeper blocks
        key, sep, value = text.partition(": ")
        if not sep:
            if text.endswith(":") and section is not None and len(headers) == depth:
                headers.append(text[:-1].strip())
            continue  # a header (or noise) carries no value itself
        key, value = key.strip(), value.strip()
        if in_errors:
            errors[key] = value
        elif section is None:
            continue
        elif headers:
            target = section
            for name in headers:
                target = target.setdefault(name, {})
                if not isinstance(target, dict):  # header clashes with a field
                    break
            else:
                target.setdefault(key, []).append(value)
        elif key in section:
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
