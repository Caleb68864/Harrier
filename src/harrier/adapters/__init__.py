"""Adapter package: one module per free OSINT tool.

Every adapter exposes ``run(selector, **opts) -> AdapterResult`` and normalizes
its tool's output into :class:`~harrier.schema.Finding` objects. The cardinal
rule (spec A-2 / graceful degradation): a missing binary, missing import, bad
selector, or tool crash must yield ``status="unavailable"`` (or ``"blocked"`` /
``"error"``) with an empty finding list — it must NEVER raise out of the sweep.

Shared plumbing lives here:
  * :func:`validate_selector` — rejects shell metacharacters (A-2).
  * :func:`run_subprocess` — list-args only, no shell, 30s timeout.
  * :class:`AdapterResult` — a list of findings that also carries ``.status``.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Iterable

from harrier.schema import Finding

# Default per-adapter subprocess timeout (seconds), per spec.
DEFAULT_TIMEOUT = 30

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
    return s


class AdapterResult(list):
    """A list of Findings that also carries the adapter's ``status``.

    Subclassing ``list`` lets callers treat the result as the findings list
    (``for f in result`` / ``result == []``) while still reading
    ``result.status`` and ``result.tool`` — satisfying both the runner and the
    ``status``-oriented acceptance tests.
    """

    def __init__(self, findings: Iterable[Finding] | None = None, *, status: str,
                 tool: str, reason: str | None = None):
        super().__init__(findings or [])
        self.status = status
        self.tool = tool
        self.reason = reason

    @property
    def findings(self) -> list[Finding]:
        return list(self)


def binary_available(name: str) -> bool:
    """True if ``name`` resolves to an executable on PATH."""
    return shutil.which(name) is not None


def run_subprocess(args: list[str], timeout: int = DEFAULT_TIMEOUT) -> subprocess.CompletedProcess:
    """Run a subprocess safely: list args, no shell, bounded timeout.

    Runs with ``shell=False`` always. Raises the usual subprocess exceptions
    (``FileNotFoundError``, ``TimeoutExpired``); adapters catch these and
    degrade. ``args`` MUST be a list.
    """
    if not isinstance(args, list):  # guardrail: never accept a shell string
        raise SelectorError("subprocess args must be a list, never a shell string")
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
        check=False,
    )
