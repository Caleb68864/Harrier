---
sub_spec_id: SS-02
phase: run
depends_on: ['SS-01']
wave: 2
---

# SS-02 — Candidate / permutation generator

## Provides
- `generate_candidates(first, last, maiden=None, married=None, nicknames=[], max=25) -> list[str]` (ranked), registered as an MCP tool.

## Requires
- SS-01 `register(app)` seam.

## Interface Contracts
### generate_candidates
- Direction: SS-02 → SS-05 (consumed by `person_sweep`)
- Owner: SS-02
- Shape: `generate_candidates(first: str, last: str, maiden: str|None, married: str|None, nicknames: list[str], max: int) -> list[str]`

## Implementation Steps (TDD)
1. **Test:** `tests/test_candidates.py::test_maiden_married_crosses` — assert output of `generate_candidates("amanda","bennett",maiden="wademan",married="warm")` includes `amanda.wademan`, `awademan`, `amandawarm`, and `len <= max`. Run → FAIL.
2. **Impl:** `src/harrier/candidates.py` — pattern set (`first.last`, `flast`, `firstl`, `f.last`, `firstlast`, initials, +common digits `1/12/123`), crossed over {last, maiden, married} and nicknames; rank by likelihood; dedup; truncate to `max`. Add `register(app)`.
3. **Run:** `uv run pytest tests/test_candidates.py` → PASS.
4. **Impl:** wire `register` into `register_all` in `server.py`.
5. **Commit:** `factory(SS-02): candidate/permutation generator [factory-managed]`

## Verification Commands
- Test: `uv run pytest tests/test_candidates.py`
- Behavior: `uv run python -c "from harrier.candidates import generate_candidates as g; print('amandawarm' in g('amanda','bennett',married='warm'))"`

## Checks
| Criterion | Type | Command |
|---|---|---|
| module exists | [STRUCTURAL] | `test -f src/harrier/candidates.py || (echo "FAIL: candidates.py" && exit 1)` |
| registered as tool | [STRUCTURAL] | `grep -q "def register" src/harrier/candidates.py || (echo "FAIL: register" && exit 1)` |
| tests pass | [MECHANICAL] | `uv run pytest tests/test_candidates.py` |
