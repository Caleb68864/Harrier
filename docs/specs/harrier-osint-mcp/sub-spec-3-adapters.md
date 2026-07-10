---
sub_spec_id: SS-03
phase: run
depends_on: ['SS-01']
wave: 2
---

# SS-03 — Free tool adapters (username / email / phone / domain)

## Provides
- `adapters.username|email|phone|domain` each with `run(selector, **opts) -> list[Finding]` + `status`.
- MCP tools `username_sweep`, `email_recon`, `phone_lookup`, `domain_harvest`.

## Requires
- SS-01 `Finding` + `register` seam.

## Decisions
- Import holehe/socialscan as libs; subprocess Sherlock/Maigret/theHarvester/PhoneInfoga.
- (A-1) Sherlock: `subprocess` list-args `["sherlock", user, "--folderoutput", tmp, "--print-found", "--timeout", "30"]`, parse the result file (no stdout JSON). Maigret: `--json simple` to temp. Default per-adapter timeout **30s**.
- (A-2) never `shell=True`; validate selectors (reject shell metacharacters) before dispatch.
- Missing binary/import → `status="unavailable"`, empty list, no raise. Single-source hit → `confidence="low"`.

## Implementation Steps (TDD)
1. **Test:** `tests/test_adapters.py::test_unavailable_binary` — monkeypatch the Sherlock path to nonexistent; assert `username.run("x").status == "unavailable"` and returns `[]`, no exception. Run → FAIL.
2. **Impl:** `src/harrier/adapters/__init__.py` (shared subprocess-safe helper + timeout); then `username.py`, `email.py`, `phone.py`, `domain.py`, each emitting `Finding`s + `status`.
3. **Run:** `uv run pytest tests/test_adapters.py` → PASS.
4. **Impl:** register the four MCP tools; wire into `register_all`.
5. **Commit:** `factory(SS-03): free tool adapters [factory-managed]`

## Verification Commands
- Test: `uv run pytest tests/test_adapters.py`

## Checks
| Criterion | Type | Command |
|---|---|---|
| adapters present | [STRUCTURAL] | `for f in username email phone domain; do test -f src/harrier/adapters/$f.py || (echo "FAIL: $f" && exit 1); done` |
| no shell=True | [STRUCTURAL] | `! grep -rq "shell=True" src/harrier/adapters || (echo "FAIL: shell=True present" && exit 1)` |
| tests pass | [MECHANICAL] | `uv run pytest tests/test_adapters.py` |
