---
sub_spec_id: SS-01
phase: run
depends_on: []
wave: 1
---

# SS-01 — Scaffold + FastMCP server + `Finding` schema

## Provides
- `Finding` pydantic model (the normalization contract for ALL adapters).
- `register_all(app) -> None` registration seam + `main()` stdio entrypoint.
- uv project layout under `src/harrier/`.

## Requires
- Nothing (foundation).

## Interface Contracts
### Finding
- Direction: SS-01 → SS-02/03/04/05 (all consumers)
- Owner: SS-01
- Shape: pydantic model `Finding(selector: str, source_tool: str, url: str|None, value: str|None, exists: bool|None, confidence: Literal["high","medium","low"], tier: Literal["free","scrape","blocked"], reason: str|None, raw: dict)`
### register seam
- Direction: SS-01 → SS-02/03/04/05
- Owner: SS-01
- Shape: each tool module exposes `register(app: FastMCP) -> None`; `register_all(app)` calls them in a list.

## Implementation Steps (TDD)
1. **Test:** `tests/test_schema.py::test_finding_defaults` — construct a `Finding` with required fields; assert `tier` accepts only the enum and `confidence` defaults sanely. Run `uv run pytest tests/test_schema.py` → FAIL (no module).
2. **Impl:** `pyproject.toml` (uv, deps: `mcp`/`fastmcp`, `pydantic`; dev: `pytest`); `src/harrier/schema.py` with the `Finding` model.
3. **Run:** `uv run pytest tests/test_schema.py` → PASS.
4. **Impl:** `src/harrier/server.py` — `create_app()` returns a FastMCP; `register_all(app)` (empty list for now); `main()` runs stdio.
5. **Test/Run:** `uv run python -c "import harrier.server"` → exit 0.
6. **Commit:** `factory(SS-01): scaffold + FastMCP server + Finding schema [factory-managed]`

## Verification Commands
- Build: `uv sync`
- Test: `uv run pytest tests/test_schema.py`
- Import: `uv run python -c "import harrier.server"`

## Checks
| Criterion | Type | Command |
|---|---|---|
| server imports | [MECHANICAL] | `uv run python -c "import harrier.server" || (echo "FAIL: import" && exit 1)` |
| Finding model exists | [STRUCTURAL] | `grep -q "class Finding" src/harrier/schema.py || (echo "FAIL: Finding" && exit 1)` |
| register_all seam | [STRUCTURAL] | `grep -q "def register_all" src/harrier/server.py || (echo "FAIL: register_all" && exit 1)` |
| schema tests pass | [MECHANICAL] | `uv run pytest tests/test_schema.py` |
