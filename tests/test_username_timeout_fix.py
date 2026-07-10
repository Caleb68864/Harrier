"""Regression tests for the username-adapter timeout fix.

Two bugs were chased down after a live sweep returned status="error":
  1. Sherlock's per-site ``--timeout`` was set to the whole budget, so the
     ~400-site sweep never finished and returned nothing.
  2. The runner's outer wait_for was shorter than the adapter's subprocess
     timeout, so a slow-but-fine run surfaced as "error" instead of a clean
     timeout/unavailable.
"""

import asyncio
import subprocess

from harrier import sweep
from harrier.adapters import username


def test_sherlock_per_site_timeout_is_small_and_overall_is_budget(monkeypatch):
    """--timeout (per-site) is small; the subprocess timeout is the full budget."""
    captured = {}

    def fake_run_subprocess(args, timeout=30):
        captured["args"] = args
        captured["timeout"] = timeout
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(username, "binary_available", lambda name: name == "sherlock")
    monkeypatch.setattr(username, "run_subprocess", fake_run_subprocess)

    username.run("awademan", timeout=60, per_site_timeout=5)

    args = captured["args"]
    i = args.index("--timeout")
    assert args[i + 1] == "5", "per-site timeout must be small, not the whole budget"
    assert captured["timeout"] == 60, "subprocess bound must be the full budget"
    # curated --site list keeps the fan-out fast (not a full ~400-site sweep)
    assert "--site" in args, "should restrict to a curated site list"
    assert "GitHub" in args


def test_sweep_classifies_timeout_as_timeout_not_error():
    """A genuine timeout is honest degradation, not a code error."""
    assert sweep._normalize("username", asyncio.TimeoutError())[1] == "timeout"
    assert sweep._normalize("username", TimeoutError())[1] == "timeout"
    # real errors are still classified as errors
    assert sweep._normalize("username", ValueError("boom"))[1] == "error"
