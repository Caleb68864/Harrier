"""Regression tests for the fan-out runner's sync boundary.

The MCP tool boundary calls ``run_jobs_sync`` while FastMCP's own event loop is
running. A bare ``asyncio.run`` there raises "cannot be called from a running
event loop" — which silently broke ``person_sweep`` / ``investigate`` in a live
server while leaving the pure-sync tools (court/manual_assist) working. These
tests pin both entry contexts.
"""

from __future__ import annotations

import asyncio

from harrier.runner import run_coro_sync, run_in_thread, run_jobs_sync


def test_run_jobs_sync_from_plain_sync_context():
    """The tests/CLI path: no loop running — runs inline."""
    assert run_jobs_sync([("a", lambda: 1), ("b", lambda: 2)]) == [("a", 1), ("b", 2)]


def test_run_jobs_sync_from_running_loop():
    """The MCP path: a loop is already running — must not raise, must return."""

    async def main():
        # Called exactly as a sync FastMCP tool body would be, mid-event-loop.
        return run_jobs_sync([("x", lambda: 42)])

    assert asyncio.run(main()) == [("x", 42)]


def test_run_jobs_sync_surfaces_exceptions_not_raise():
    """A failing job comes back as the exception object, never crashes the sweep."""

    def boom():
        raise ValueError("nope")

    out = dict(run_jobs_sync([("good", lambda: 5), ("bad", boom)]))
    assert out["good"] == 5
    assert isinstance(out["bad"], ValueError)


async def _echo(v):
    return v


def test_run_in_thread_inline_and_in_loop():
    """Sync-only work (e.g. Playwright sync API) runs off a running loop."""
    import threading

    # No loop: runs inline on the calling thread.
    assert run_in_thread(lambda: threading.current_thread().name) == \
        threading.current_thread().name

    # In-loop: must offload to a DIFFERENT thread (where sync-only libs are legal).
    async def main():
        return run_in_thread(lambda: threading.current_thread().name)

    assert asyncio.run(main()) != threading.current_thread().name


def test_run_coro_sync_inline_and_in_loop():
    """The shared sync↔async choke point works in both contexts (holehe uses it)."""
    # sync context
    assert run_coro_sync(lambda: _echo(5)) == 5

    # in-loop context (the direct-tool path that would otherwise silently no-op)
    async def main():
        return run_coro_sync(lambda: _echo(7))

    assert asyncio.run(main()) == 7


# --- O2: a runner timeout must stop the work, not just the wait -------------

import os
import sys
import time

import pytest

from harrier.adapters import run_subprocess
from harrier.runner import (JobBudget, _JOB_BUDGET, current_budget,
                            job_remaining, run_jobs)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:  # a zombie is dead for our purposes
        with open(f"/proc/{pid}/stat") as fh:
            return fh.read().split(")")[-1].split()[0] != "Z"
    except OSError:
        return True


def _wait_dead(pids, within=3.0) -> list[int]:
    end = time.monotonic() + within
    while time.monotonic() < end:
        alive = [p for p in pids if _alive(p)]
        if not alive:
            return []
        time.sleep(0.05)
    return [p for p in pids if _alive(p)]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_timed_out_subprocess_and_its_children_are_killed(tmp_path):
    pidfile = tmp_path / "pids"
    # The tool starts a child of its own (like sherlock's workers would) and
    # both would outlive the runner's 1s budget by a lot.
    script = f'sleep 20 & echo $$ $! > {pidfile}; wait'

    def job():
        return run_subprocess(["sh", "-c", script], timeout=60)

    async def main():
        start = time.monotonic()
        out = await run_jobs([("slow", job)], timeout=1, jitter=0)
        elapsed = time.monotonic() - start
        for _ in range(40):  # the shell writes its pids almost at once
            if pidfile.exists() and pidfile.read_text().strip():
                break
            time.sleep(0.05)
        pids = [int(p) for p in pidfile.read_text().split()]
        # Checked BEFORE asyncio.run's executor shutdown can wait for the thread.
        return out, elapsed, pids, _wait_dead(pids)

    start = time.monotonic()
    out, elapsed, pids, still_alive = asyncio.run(main())
    total = time.monotonic() - start
    assert isinstance(out[0][1], TimeoutError)
    assert elapsed < 3
    assert len(pids) == 2
    assert still_alive == [], f"timed-out job left processes running: {still_alive}"
    assert total < 5  # nothing kept the sync boundary waiting on the old job


def test_subprocess_timeout_from_the_job_budget_is_a_job_timeout():
    """O19: run_subprocess's timeout is capped to the job budget, so it can
    fire a hair before wait_for does. That must still read as the runner's
    TimeoutError (sweep status "timeout"), not a TimeoutExpired ("error").
    Forced deterministically: the job spends its budget, then raises."""
    import subprocess

    def job():
        current_budget().deadline = time.monotonic() - 0.01  # budget spent
        raise subprocess.TimeoutExpired(["tool"], 0.99)

    [(_, result)] = asyncio.run(run_jobs([("slow", job)], timeout=30, jitter=0))
    assert isinstance(result, TimeoutError)
    assert isinstance(result.__cause__, subprocess.TimeoutExpired)


def test_subprocess_own_short_timeout_keeps_its_type():
    """A tool's own timeout well inside the job budget is not a job timeout."""
    import subprocess

    def job():
        raise subprocess.TimeoutExpired(["tool"], 0.1)

    [(_, result)] = asyncio.run(run_jobs([("t", job)], timeout=30, jitter=0))
    assert type(result) is subprocess.TimeoutExpired


def test_job_remaining_reflects_the_job_deadline():
    assert job_remaining(30) == 30  # outside a job: unchanged
    token = _JOB_BUDGET.set(JobBudget(deadline=time.monotonic() + 2))
    try:
        assert 0 < job_remaining(30) <= 2
        _JOB_BUDGET.get().cancel.set()
        assert job_remaining(30) == 0
    finally:
        _JOB_BUDGET.reset(token)


def test_people_search_navigation_is_capped_to_job_budget(monkeypatch):
    from harrier.adapters import people_search

    seen = {}

    class Page:
        def goto(self, url, timeout, **k):
            seen["timeout"] = timeout

            class R:
                status = 200
            return R()

        def content(self):
            return "<html></html>"

    class Browser:
        def new_context(self, **k):
            return type("C", (), {"new_page": lambda self: Page()})()

        def close(self):
            pass

    class PW:
        chromium = type("Ch", (), {"launch": lambda self, **k: Browser()})()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    token = _JOB_BUDGET.set(JobBudget(deadline=time.monotonic() + 2))
    try:
        people_search._fetch(PW, "Jane Doe", None, "example.invalid")
    finally:
        _JOB_BUDGET.reset(token)
    assert 0 < seen["timeout"] <= 2000
