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

# Bounds for the holehe pass (~120 sites). Concurrency keeps it fast without
# hammering; the budget hard-caps wall-clock so a hung site can't stall a sweep.
_HOLEHE_CONCURRENCY = 25
_HOLEHE_BUDGET = 45  # seconds


def _validate_email(email: str) -> str:
    if not isinstance(email, str) or not _EMAIL_RE.match(email.strip()):
        raise SelectorError(f"not a valid email: {email!r}")
    return email.strip().lower()


def _note(errors: list[str] | None, msg: str) -> None:
    if errors is not None:
        errors.append(msg)


def _exc_text(exc: BaseException) -> str:
    msg = str(exc).strip()
    return f"{type(exc).__name__}: {msg[:200]}" if msg else type(exc).__name__


def _run_holehe(email: str, errors: list[str] | None = None,
                notes: list[str] | None = None) -> list[Finding]:
    """Run holehe over its module set. Returns [] if holehe is unusable.

    Failure causes are appended to ``errors`` (if given) so the caller can
    report *why* the pass yielded nothing instead of a silent ``ok``.
    """
    try:
        import httpx
        from holehe.core import import_submodules, get_functions
    except Exception as exc:  # noqa: BLE001 — missing/incompatible import → degrade
        _note(errors, f"holehe import failed ({_exc_text(exc)})")
        return []

    import asyncio

    # Bound the whole holehe pass: run the ~120 site checks CONCURRENTLY (the
    # original loop awaited them one-by-one → minutes of wall-clock), cap
    # concurrency for politeness, and hard-stop the whole thing at _HOLEHE_BUDGET
    # so a slow/hung site can never stall the sweep.
    async def _gather() -> list[dict]:
        modules = import_submodules("holehe.modules")
        funcs = get_functions(modules)
        results: list[dict] = []
        sem = asyncio.Semaphore(_HOLEHE_CONCURRENCY)

        async def _one(func, client) -> None:
            sub: list[dict] = []
            async with sem:
                try:
                    await func(email, client, sub)
                except Exception:  # noqa: BLE001 — one site failing is fine
                    return
            results.extend(sub)

        async with httpx.AsyncClient() as client:
            await asyncio.gather(*(_one(f, client) for f in funcs),
                                 return_exceptions=True)
        return results

    try:
        # Loop-safe: works whether called from a worker thread (person_sweep
        # fan-out) or in-loop (the direct email_recon MCP tool). A bare
        # asyncio.run here would silently no-op in the running server loop.
        from harrier.runner import run_coro_sync
        raw = run_coro_sync(
            lambda: asyncio.wait_for(_gather(), timeout=_HOLEHE_BUDGET))
    except (asyncio.TimeoutError, TimeoutError):
        _note(errors, f"holehe exceeded its {_HOLEHE_BUDGET}s budget; no results")
        return []
    except Exception as exc:  # noqa: BLE001 — degrade to []
        _note(errors, f"holehe failed ({_exc_text(exc)})")
        return []

    findings: list[Finding] = []
    rate_limited = sorted(
        str(e.get("name") or e.get("domain") or "?") for e in raw or []
        if isinstance(e, dict) and e.get("rateLimit") is True)
    if rate_limited:
        # A rate-limited site reports exists=False — that is "unknown", not a
        # negative. Say so, so the agent doesn't read it as "not registered".
        shown = ", ".join(rate_limited[:10]) + (" ..." if len(rate_limited) > 10 else "")
        _note(notes, f"holehe: {len(rate_limited)} site(s) rate-limited, "
                     f"result unknown ({shown})")
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


def _run_socialscan(email: str, errors: list[str] | None = None) -> list[Finding]:
    """Run socialscan for the email. Returns [] if unusable (cause → ``errors``)."""
    try:
        from socialscan.util import Platforms, sync_execute_queries
    except Exception as exc:  # noqa: BLE001
        _note(errors, f"socialscan import failed ({_exc_text(exc)})")
        return []

    try:
        # Loop-safe: sync_execute_queries calls asyncio.run() internally, which
        # raises inside FastMCP's running loop (the direct email_recon tool) —
        # offload it exactly like the holehe pass.
        from harrier.runner import run_in_thread
        results = run_in_thread(lambda: sync_execute_queries(
            [email], [Platforms.GITHUB, Platforms.INSTAGRAM]))
    except Exception as exc:  # noqa: BLE001
        _note(errors, f"socialscan failed ({_exc_text(exc)})")
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
    errors: list[str] = []
    notes: list[str] = []
    if holehe_ok:
        findings.extend(_run_holehe(email, errors, notes))
    if socialscan_ok:
        findings.extend(_run_socialscan(email, errors))
    reason = "; ".join(errors + notes) or None
    attempted = int(holehe_ok) + int(socialscan_ok)
    if not findings and len(errors) >= attempted:
        # Every installed backend failed: that is an error, not "not found".
        return AdapterResult(status="error", tool=TOOL, reason=reason)
    return AdapterResult(findings, status="ok", tool=TOOL, reason=reason)


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
