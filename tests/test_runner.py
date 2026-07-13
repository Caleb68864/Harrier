"""Regression tests for the fan-out runner's sync boundary.

The MCP tool boundary calls ``run_jobs_sync`` while FastMCP's own event loop is
running. A bare ``asyncio.run`` there raises "cannot be called from a running
event loop" — which silently broke ``person_sweep`` / ``investigate`` in a live
server while leaving the pure-sync tools (court/manual_assist) working. These
tests pin both entry contexts.
"""

from __future__ import annotations

import asyncio

from harrier.runner import run_coro_sync, run_jobs_sync


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


def test_run_coro_sync_inline_and_in_loop():
    """The shared sync↔async choke point works in both contexts (holehe uses it)."""
    # sync context
    assert run_coro_sync(lambda: _echo(5)) == 5

    # in-loop context (the direct-tool path that would otherwise silently no-op)
    async def main():
        return run_coro_sync(lambda: _echo(7))

    assert asyncio.run(main()) == 7
