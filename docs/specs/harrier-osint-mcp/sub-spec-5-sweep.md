---
sub_spec_id: SS-05
phase: run
depends_on: ['SS-02', 'SS-03', 'SS-04']
wave: 3
---

# SS-05 — Fan-out runner + correlator + `person_sweep`

## Provides
- `person_sweep(...)` MCP tool — the high-level orchestrator (the integration seam).

## Requires
- SS-02 `generate_candidates`; SS-03 adapters (`username/email/phone/domain`); SS-04 `people_search`; SS-01 `Finding`.

## Interface Contracts
### person_sweep
- Direction: SS-05 → SS-06 (consumed by the `/osint` skill)
- Owner: SS-05
- Shape: `person_sweep(name, city=None, state=None, maiden=None, nicknames=[], email=None, phone=None, permute=True, depth="quick", consent=False) -> {"findings": list[Finding], "sources": list[{tool,status,count}], "candidates": list[str]}`

## Implementation Steps (TDD)
1. **Test:** `tests/test_sweep.py::test_integration_fanout` — stub adapters to return fixtures; assert `person_sweep` calls `generate_candidates` then each adapter and returns merged `findings`, `sources[]`, `candidates[]`. Run → FAIL.
2. **Impl:** `src/harrier/runner.py` — async concurrency-capped executor (config cap + jitter, per-adapter 30s timeout).
3. **Impl:** `src/harrier/correlate.py` — dedup; `confidence="high"` when ≥2 independent sources agree, else `"low"`.
4. **Impl:** `src/harrier/sweep.py` — `person_sweep` wiring candidates → runner → correlate; `quick`/`deep` sets the budget; register MCP tool.
5. **Test:** `test_all_unavailable` (A-3) — all adapters `unavailable` → empty findings, all `sources` `unavailable`, no raise. `test_confidence_by_agreement` — 2 sources → high, 1 → low. Run → PASS.
6. **Commit:** `factory(SS-05): fan-out + correlate + person_sweep [factory-managed]`

## Verification Commands
- Test: `uv run pytest tests/test_sweep.py`

## Checks
| Criterion | Type | Command |
|---|---|---|
| runner + correlate + sweep exist | [STRUCTURAL] | `for f in runner correlate sweep; do test -f src/harrier/$f.py || (echo "FAIL: $f" && exit 1); done` |
| person_sweep registered | [STRUCTURAL] | `grep -q "person_sweep" src/harrier/sweep.py || (echo "FAIL: person_sweep" && exit 1)` |
| concurrency cap present | [STRUCTURAL] | `grep -qiE "semaphore|concurrency|max_concurren" src/harrier/runner.py || (echo "FAIL: cap" && exit 1)` |
| tests pass | [MECHANICAL] | `uv run pytest tests/test_sweep.py` |
