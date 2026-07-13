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


def run_in_thread(fn: Callable[[], Any]) -> Any:
    """Run a blocking callable, offloading to a worker thread iff a loop runs.

    The single choke point for the "sync code that must NOT run inside an asyncio
    loop" hazard. FastMCP invokes sync tool bodies while its own loop is running;
    in that context ``asyncio.run`` raises and the Playwright **sync** API raises
    ("Sync API inside the asyncio loop"). Both work fine in a thread with no
    running loop, so: run ``fn`` inline when no loop is running, else offload to a
    fresh worker thread. Callers that already run in a worker thread (the fan-out
    jobs) see no loop and pay nothing.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return fn()  # no loop in this thread — safe to run inline

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(fn).result()


def run_coro_sync(make_coro: Callable[[], Any]) -> Any:
    """Drive an async coroutine to completion from sync code, loop-safe.

    ``make_coro`` is a zero-arg factory returning a fresh coroutine (not a
    coroutine object — so an offload never awaits a spent one). Built on
    :func:`run_in_thread`, so a bare ``asyncio.run`` never fires inside a
    already-running loop. Used by the fan-out runner and the holehe email check.
    """
    return run_in_thread(lambda: asyncio.run(make_coro()))


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
