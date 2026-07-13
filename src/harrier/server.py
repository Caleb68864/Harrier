"""Harrier FastMCP stdio server.

This module owns the registration seam. Each tool module exposes
`register(app: FastMCP) -> None`; `register_all(app)` calls them in a list so
adding a dimension is a one-line change here. `main()` starts a stdio server.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP


def create_app() -> FastMCP:
    """Build the FastMCP app and register every tool module onto it."""
    app = FastMCP("harrier")
    register_all(app)
    return app


def register_all(app: FastMCP) -> None:
    """Register all tool modules onto `app`.

    Each entry is a module with a `register(app)` function. Imports are local so
    the server still starts even if an optional dependency is missing at import
    time (adapters degrade to `unavailable` at call time, not import time).
    """
    from harrier import assist, candidates, investigate
    from harrier.adapters import court, domain, email, genealogy, phone, username
    from harrier.adapters import people_search
    from harrier import graph, sweep

    modules = [
        candidates,
        username,
        email,
        phone,
        domain,
        people_search,
        court,
        genealogy,
        assist,
        sweep,
        investigate,
        graph,
    ]
    for module in modules:
        register = getattr(module, "register", None)
        if callable(register):
            register(app)


def main() -> None:
    """Entrypoint: run the Harrier MCP server over stdio."""
    app = create_app()
    app.run()


if __name__ == "__main__":
    main()
