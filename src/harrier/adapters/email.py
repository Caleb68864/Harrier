"""Email adapter — holehe and socialscan, imported as libraries.

Both are optional. If neither imports, the adapter degrades to
``status="unavailable"`` with no findings. Any runtime error (network, API
drift) is caught and downgraded — the sweep never crashes on the email
dimension.

holehe checks whether an email is registered on ~120 sites; socialscan checks
email/username availability on a handful of platforms. We emit an ``exists``
Finding per positive hit.
"""

from __future__ import annotations

import re

from harrier.adapters import AdapterResult, SelectorError
from harrier.schema import Finding

TOOL = "email"

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email(email: str) -> str:
    if not isinstance(email, str) or not _EMAIL_RE.match(email.strip()):
        raise SelectorError(f"not a valid email: {email!r}")
    return email.strip().lower()


def _run_holehe(email: str) -> list[Finding]:
    """Run holehe over its module set. Returns [] if holehe is unusable."""
    try:
        import asyncio

        import httpx
        from holehe.core import import_submodules, get_functions
    except Exception:  # noqa: BLE001 — missing/incompatible import → degrade
        return []

    async def _gather() -> list[dict]:
        modules = import_submodules("holehe.modules")
        funcs = get_functions(modules)
        out: list[dict] = []
        async with httpx.AsyncClient() as client:
            results: list[dict] = []
            import inspect

            for func in funcs:
                sub: list[dict] = []
                try:
                    await func(email, client, sub)
                except Exception:  # noqa: BLE001 — one site failing is fine
                    continue
                results.extend(sub)
            out = results
        return out

    try:
        raw = asyncio.run(_gather())
    except Exception:  # noqa: BLE001
        return []

    findings: list[Finding] = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("exists") is True:
            findings.append(
                Finding(
                    selector=email,
                    source_tool="holehe",
                    url=None,
                    value=entry.get("name"),
                    exists=True,
                    confidence="low",
                    tier="free",
                    raw=entry,
                )
            )
    return findings


def _run_socialscan(email: str) -> list[Finding]:
    """Run socialscan for the email. Returns [] if unusable."""
    try:
        from socialscan.util import Platforms, sync_execute_queries
    except Exception:  # noqa: BLE001
        return []

    try:
        results = sync_execute_queries([email], [Platforms.GITHUB, Platforms.INSTAGRAM])
    except Exception:  # noqa: BLE001
        return []

    findings: list[Finding] = []
    for r in results or []:
        # available == False means the email/username is taken → it exists.
        exists = getattr(r, "available", None)
        if exists is False and getattr(r, "success", False):
            findings.append(
                Finding(
                    selector=email,
                    source_tool="socialscan",
                    url=None,
                    value=str(getattr(r, "platform", "")),
                    exists=True,
                    confidence="low",
                    tier="free",
                    raw={"platform": str(getattr(r, "platform", ""))},
                )
            )
    return findings


def run(selector: str, **opts) -> AdapterResult:
    """Check an email across holehe + socialscan.

    Both are best-effort; if neither yields a usable result AND neither library
    is importable, the status is ``unavailable``.
    """
    try:
        email = _validate_email(selector)
    except SelectorError as exc:
        return AdapterResult(status="error", tool=TOOL, reason=str(exc))

    # Detect library availability so we can distinguish "ran, found nothing"
    # from "tool not installed".
    holehe_ok = _lib_importable("holehe.core")
    socialscan_ok = _lib_importable("socialscan.util")
    if not holehe_ok and not socialscan_ok:
        return AdapterResult(
            status="unavailable",
            tool=TOOL,
            reason="no email tool available (install holehe or socialscan)",
        )

    findings: list[Finding] = []
    findings.extend(_run_holehe(email))
    findings.extend(_run_socialscan(email))
    return AdapterResult(findings, status="ok", tool=TOOL)


def _lib_importable(module: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(module) is not None
    except Exception:  # noqa: BLE001
        return False


def register(app) -> None:
    """Register the `email_recon` MCP tool."""

    @app.tool(name="email_recon")
    def email_recon(selector: str) -> dict:
        """Check whether an email is registered across free OSINT sources."""
        res = run(selector)
        return {
            "status": res.status,
            "count": len(res),
            "findings": [f.model_dump() for f in res],
            "reason": res.reason,
        }
