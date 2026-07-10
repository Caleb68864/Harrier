---
sub_spec_id: SS-04
phase: run
depends_on: ['SS-01']
wave: 2
---

# SS-04 — People-search browser module (spike + consent-gated adapter)

## Provides
- `adapters.people_search.run(name, city_or_state=None, age=None, consent=False) -> {findings, status}`, MCP tool `people_search`.
- `docs/ss04-spike-evidence.md` (the ASM-1 gate).

## Requires
- SS-01 `Finding` + `register` seam.

## Decisions
- **Spike FIRST:** attempt one free people-search site (start TruePeopleSearch or FastPeopleSearch) via Playwright; record reachability in `docs/ss04-spike-evidence.md`. Stealth starts plain, escalates only if needed.
- `consent=False` → return `status="blocked"`, `tier="blocked"`, **no network call**.
- On 403/CAPTCHA → return a `blocked` `Finding` whose `reason` is the manual step (never raise). Rate-limit + jitter.

## Implementation Steps (TDD)
1. **Spike:** run a throwaway Playwright fetch against the chosen site; write `docs/ss04-spike-evidence.md` (site, reachable? stealth needed?). **If unreachable → STOP, escalate (value-prop gate).**
2. **Test:** `tests/test_people_search.py::test_consent_gate` — `people_search(consent=False)` returns `status="blocked"` and makes no network call (assert via mocked browser). Run → FAIL.
3. **Impl:** `src/harrier/adapters/people_search.py` — consent gate, Playwright fetch, parse address/relatives/phone → `Finding`s tier `scrape`; 403/CAPTCHA → `blocked` Finding with manual-step `reason`.
4. **Test:** `test_block_on_captcha` — simulate 403 → returns `blocked` Finding, no raise. Run → PASS.
5. **Impl:** register `people_search`; wire into `register_all`.
6. **Commit:** `factory(SS-04): people-search spike + consent-gated adapter [factory-managed]`

## Verification Commands
- Test: `uv run pytest tests/test_people_search.py`
- Gate: review `docs/ss04-spike-evidence.md`

## Checks
| Criterion | Type | Command |
|---|---|---|
| spike evidence exists | [STRUCTURAL] | `test -f docs/ss04-spike-evidence.md || (echo "FAIL: spike evidence" && exit 1)` |
| adapter exists | [STRUCTURAL] | `test -f src/harrier/adapters/people_search.py || (echo "FAIL: people_search" && exit 1)` |
| consent gate present | [STRUCTURAL] | `grep -q "consent" src/harrier/adapters/people_search.py || (echo "FAIL: consent gate" && exit 1)` |
| tests pass | [MECHANICAL] | `uv run pytest tests/test_people_search.py` |
