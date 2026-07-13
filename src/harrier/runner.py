"""Concurrency-capped async fan-out runner (SS-05).

Adapters are blocking (subprocess / requests / Playwright), so each job runs in
a worker thread via ``asyncio.to_thread``, gated by a semaphore so we never open
more than ``max_concurrency`` connections from the host IP at once. A small
random jitter before each job spreads requests out (politeness / anti-rate-limit).

A job is a ``(tool_name, callable)`` pair where the callable takes no args and
returns the adapter's result. The runner never lets one job's exception escape:
failures come back as the exception object, and the caller decides how to
normalize them (typically to a ``sources[]`` entry, never a crash).
"""

from __future__ import annotations

import asyncio
import random
from typing import Any, Callable, Sequence

# Default global cap on concurrent outbound jobs from this host.
DEFAULT_MAX_CONCURRENCY = 5
DEFAULT_TIMEOUT = 30
DEFAULT_JITTER = 0.3  # seconds; actual delay is uniform(0, jitter)

Job = tuple[str, Callable[[], Any]]


async def run_jobs(
    jobs: Sequence[Job],
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    timeout: int = DEFAULT_TIMEOUT,
    jitter: float = DEFAULT_JITTER,
) -> list[tuple[str, Any]]:
    """Run jobs concurrently under a semaphore cap; return ``(tool, result)``.

    ``result`` is the callable's return value, or the raised exception object if
    it failed / timed out. Order matches ``jobs``.
    """
    if not jobs:
        return []
    sem = asyncio.Semaphore(max(1, max_concurrency))

    async def _one(tool: str, fn: Callable[[], Any]) -> tuple[str, Any]:
        async with sem:
            if jitter:
                await asyncio.sleep(random.random() * jitter)
            try:
                return tool, await asyncio.wait_for(
                    asyncio.to_thread(fn), timeout=timeout
                )
            except Exception as exc:  # noqa: BLE001 — surfaced, never raised out
                return tool, exc

    return await asyncio.gather(*[_one(tool, fn) for tool, fn in jobs])


def run_coro_sync(make_coro: Callable[[], Any]) -> Any:
    """Run an async coroutine to completion from sync code, loop-safe.

    ``make_coro`` is a zero-arg callable that returns a fresh coroutine (a
    factory, not a coroutine object — so a retry/offload never awaits a spent
    coroutine). Works from BOTH a plain sync caller (tests, CLI) and from inside
    an already-running event loop: FastMCP invokes sync tool bodies while its own
    loop is running, and a bare ``asyncio.run`` there raises "cannot be called
    from a running event loop". When a loop is already running we offload to a
    worker thread that owns a fresh loop; otherwise we run inline.

    This is the single choke point for the sync↔async boundary — every sync
    entrypoint that needs to drive a coroutine (the fan-out runner, the holehe
    email check) goes through here so the event-loop hazard is fixed in one place.
    """
    def _run() -> Any:
        return asyncio.run(make_coro())

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _run()  # no loop in this thread — safe to run inline

    # A loop is already running in this thread (the MCP async context). Run in a
    # separate thread so its `asyncio.run` gets a clean loop.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_run).result()


def run_jobs_sync(
    jobs: Sequence[Job],
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    timeout: int = DEFAULT_TIMEOUT,
    jitter: float = DEFAULT_JITTER,
) -> list[tuple[str, Any]]:
    """Synchronous, loop-safe wrapper around :func:`run_jobs` for the MCP tool
    boundary. See :func:`run_coro_sync` for why the loop check is required."""
    return run_coro_sync(
        lambda: run_jobs(jobs, max_concurrency=max_concurrency,
                         timeout=timeout, jitter=jitter)
    )
