"""Adapter package: one module per free OSINT tool.

Every adapter exposes ``run(selector, **opts) -> AdapterResult`` and normalizes
its tool's output into :class:`~harrier.schema.Finding` objects. The cardinal
rule (spec A-2 / graceful degradation): a missing binary, missing import, bad
selector, or tool crash must yield ``status="unavailable"`` (or ``"blocked"`` /
``"error"``) with an empty finding list — it must NEVER raise out of the sweep.
A tool that overruns its own timeout is ``"timeout"``, the same word the sweep
uses for a job that overruns the runner's budget (roadmap O32).

Shared plumbing lives here:
  * :func:`validate_selector` — rejects shell metacharacters (A-2).
  * :func:`run_subprocess` — list-args only, no shell, 30s timeout.
  * :class:`AdapterResult` — a list of findings that also carries ``.status``.
"""

from __future__ import annotations

import functools
import logging
import os
import shutil
import signal
import subprocess
import time
from typing import Any, Callable, Iterable

from harrier.schema import Finding

# Default per-adapter subprocess timeout (seconds), per spec.
DEFAULT_TIMEOUT = 30
# Bounds for caller-supplied timeouts: <=0 would "time out" instantly (a fake
# unavailable), and an unbounded value could hang a direct MCP tool call.
MIN_TIMEOUT = 1
MAX_TIMEOUT = 300


def clamp_timeout(timeout, default: int = DEFAULT_TIMEOUT) -> int:
    """Coerce a caller-supplied timeout to an int in [MIN_TIMEOUT, MAX_TIMEOUT]."""
    try:
        t = int(timeout)
    except (TypeError, ValueError):
        t = default
    return max(MIN_TIMEOUT, min(MAX_TIMEOUT, t))

# Characters that must never reach a selector we hand to a subprocess or URL.
# We pass args as a list (no shell), but validating anyway is defense in depth.
# Path separators (`/`, `\`) are included: a selector becomes part of a temp
# result-file path (username.py), so `../x` would traverse outside the temp dir
# on the read side. Usernames/domains never legitimately contain a slash.
_SHELL_METACHARS = set(";&|`$><\n\r\t\\/\"'(){}[]!*?~")


class SelectorError(ValueError):
    """Raised internally when a selector fails validation; never escapes run()."""


def validate_selector(selector: str) -> str:
    """Return the stripped selector, or raise SelectorError on unsafe input.

    Rejects empty selectors and any containing shell metacharacters or
    whitespace. Callers convert the exception into an ``unavailable``/``error``
    result rather than letting it propagate.
    """
    if not isinstance(selector, str):
        raise SelectorError("selector must be a string")
    s = selector.strip()
    if not s:
        raise SelectorError("empty selector")
    if any(ch in _SHELL_METACHARS for ch in s):
        raise SelectorError(f"selector contains disallowed characters: {selector!r}")
    if any(ch.isspace() for ch in s):
        raise SelectorError("selector contains whitespace")
    if s.startswith("-"):
        # The selector is a positional argv entry; a leading dash would be parsed
        # by sherlock/maigret/theHarvester as an OPTION (argument injection,
        # e.g. ``--output=x``) rather than a username/domain.
        raise SelectorError(f"selector may not start with '-': {selector!r}")
    return s


class AdapterResult(list):
    """A list of Findings that also carries the adapter's ``status``.

    Subclassing ``list`` lets callers treat the result as the findings list
    (``for f in result`` / ``result == []``) while still reading
    ``result.status`` and ``result.tool`` — satisfying both the runner and the
    ``status``-oriented acceptance tests.
    """

    def __init__(self, findings: Iterable[Finding] | None = None, *, status: str,
                 tool: str, reason: str | None = None,
                 next_steps: Iterable[str] | None = None):
        super().__init__(findings or [])
        self.status = status
        self.tool = tool
        self.reason = reason
        # Things for the analyst to do by hand (e.g. searches to run); not
        # findings, because nothing was observed.
        self.next_steps = list(next_steps or [])

    @property
    def findings(self) -> list[Finding]:
        return list(self)


# Statuses that are not a degradation (blocked = a manual step, by design).
_HEALTHY = {"ok", "empty", "blocked"}


def _outcome(result: Any) -> tuple[str | None, str | None]:
    """``(status, reason)`` of an adapter return (AdapterResult or the
    people_search dict)."""
    if isinstance(result, AdapterResult):
        return result.status, result.reason
    if isinstance(result, dict):
        reason = result.get("reason")
        if not isinstance(reason, str):
            reason = next((f.reason for f in result.get("findings") or []
                           if getattr(f, "reason", None)), None)
        return result.get("status"), reason
    return None, None


def log_outcome(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Log an adapter ``run()``'s degraded outcomes to ``harrier.adapters.<name>``.

    Stdio MCP: stdout is the protocol channel, so this goes through logging
    (stderr). error/unavailable/timeout log at WARNING; a healthy status that
    still carries a reason (partial failure, rate limits) logs at INFO;
    ``blocked`` (a manual step by design) is not logged. An exception escaping ``run()`` (a contract breach) is
    logged and re-raised. Selectors are not logged.
    """
    log = logging.getLogger(fn.__module__)

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            result = fn(*args, **kwargs)
        except Exception:
            log.exception("adapter raised (contract breach)")
            raise
        status, reason = _outcome(result)
        if status is not None and status not in _HEALTHY:
            log.warning("adapter degraded status=%s reason=%s", status,
                        reason or "unspecified")
        elif reason and status != "blocked":
            # A blocked result's reason is the manual step, which quotes the
            # searched name; it's by design, so leave it out of the log.
            log.info("adapter note status=%s reason=%s", status, reason)
        return result

    return wrapper


def binary_available(name: str) -> bool:
    """True if ``name`` resolves to an executable on PATH."""
    return shutil.which(name) is not None


def run_subprocess(args: list[str], timeout: int = DEFAULT_TIMEOUT,
                   env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run a subprocess safely: list args, no shell, bounded timeout.

    Runs with ``shell=False`` always; ``env`` replaces the environment
    (``None`` inherits it). Raises the usual subprocess exceptions
    (``FileNotFoundError``, ``TimeoutExpired``); adapters catch these and
    degrade. ``args`` MUST be a list.

    Inside a runner job the timeout is also capped to the job's remaining
    budget, and the process is killed as soon as the job is cancelled (the
    runner gave up waiting), so a timed-out sweep leaves nothing running.
    """
    if not isinstance(args, list):  # guardrail: never accept a shell string
        raise SelectorError("subprocess args must be a list, never a shell string")
    from harrier.runner import job_remaining

    return _run_killable(args, job_remaining(clamp_timeout(timeout)), env)


_POLL = 0.1  # seconds between cancel checks


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the tool and anything it spawned (it runs in its own session)."""
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _run_killable(args: list[str], limit: float,
                  env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """``subprocess.run`` that also stops when the current runner job is
    cancelled, and kills the whole process group (not just the child)."""
    from harrier.runner import job_cancelled

    if limit <= 0:
        raise subprocess.TimeoutExpired(args, 0)
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
        env=env,  # None: inherit
        start_new_session=(os.name == "posix"),
    )
    deadline = time.monotonic() + limit
    try:
        while True:
            left = deadline - time.monotonic()
            try:
                out, err = proc.communicate(timeout=max(0.01, min(_POLL, left)))
                break
            except subprocess.TimeoutExpired:
                if job_cancelled() or time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(args, limit) from None
    except BaseException:
        _kill_tree(proc)
        proc.communicate()  # reap; pipes close once the group is dead
        raise
    return subprocess.CompletedProcess(args, proc.returncode, out, err)


def as_text(value) -> str | None:
    """Coerce an untrusted tool/API field to ``str`` (or None).

    Tool and API output drifts; a dict/int where a string was expected must not
    raise a pydantic ValidationError out of an adapter. Strings pass through,
    scalars are stringified, containers/None become None.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return None


def exit_failure_reason(tool: str, proc: subprocess.CompletedProcess,
                        limit: int = 300) -> str | None:
    """Return an actionable reason if ``proc`` exited non-zero, else None.

    Includes the exit code and the tail of stderr (or stdout) so the calling
    agent can tell "tool ran, found nothing" apart from "tool failed".
    """
    rc = getattr(proc, "returncode", 0)
    if not rc:
        return None
    detail = (getattr(proc, "stderr", "") or getattr(proc, "stdout", "") or "").strip()
    if len(detail) > limit:
        detail = "..." + detail[-limit:]
    msg = f"{tool} failed (exit {rc})"
    return f"{msg}: {detail}" if detail else msg
