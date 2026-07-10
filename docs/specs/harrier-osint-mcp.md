# Harrier — OSINT MCP — Spec

## Meta
- Client: Personal
- Project: Harrier (OSINT MCP)
- Repo: `C:\Users\CalebBennett\Documents\GitHub\harrier` (greenfield — created at run time)
- Date: 2026-07-10
- Author: Caleb Bennett
- Source design: [[Harrier — OSINT MCP Design]] (evaluated)
- Quality scores (/35): Outcome 5 · Scope 5 · Decision guidance 5 · Edge coverage 4 · Acceptance criteria 4 · Decomposition 4 · Purpose alignment 5 = **32/35**

## Outcome
A running Python/FastMCP server `harrier-mcp` that, given a person + selectors, generates ranked name/handle permutations, fans them out across free OSINT tools + ≥1 free people-search source, and returns normalized, tier-tagged, confidence-rated findings. The `/osint` skill's `--deep` mode auto-detects Harrier and uses it, degrading to web-only when absent. Success = on an Amanda-class target it surfaces materially more than web-only, OR reports each source `blocked` with a manual step — never a silent empty result.

## Intent
- **Trade-off hierarchy:** correctness + honesty (no fabricated findings, tier-tag everything) > coverage > speed. Graceful degradation > completeness.
- **Decision boundaries:** the agent decides internal layout, permutation rules, parsing, concurrency values within caps. It escalates if the ASM-1 spike shows no free people-search source is scrapable, if a tool needs paid/credentialed access, or if a contract (`Finding`/tool signatures) must change.

## Context
Extends the web-only `/osint` skill (`~/.claude/skills/osint/SKILL.md`), which underdelivered because it couldn't reach the aggregator/people-search layer and ran single naive queries. Tool interfaces + access-tier/legal caveats are documented in `Software/OSINT/` (see [[OSINT — MOC]], [[OSINT Tool Categories — Overview]], [[OSINT — Practical Access Notes (Field-Tested)]]). Mirror `FoundryMCP` conventions for the server shell. Free sources only; no paid APIs, no credentials, no logins.

## Requirements
1. FastMCP stdio server exposing the committed tool surface, installable via `uv`.
2. A single `Finding` schema every adapter normalizes to.
3. A permutation generator that expands name(+maiden/married/nicknames) into ranked handle/email candidates, capped.
4. Free tool adapters: username (Sherlock/Maigret), email (holehe/socialscan), phone (PhoneInfoga), domain (theHarvester); each emits `Finding`s and never crashes the sweep on failure (`status: unavailable`).
5. A Playwright people-search module (≥1 free site) that is consent-gated and tier-tags results `scrape`/`blocked`, preceded by a validation spike.
6. A fan-out runner + correlator that dispatches (tool × candidate) with concurrency caps + jitter, dedups, and sets confidence by cross-source agreement, exposed as `person_sweep`.
7. `/osint` skill integration via a flag (`--deep` auto-detects Harrier; `--no-mcp` override) — not a new skill.

---

## Sub-Specs

---
sub_spec_id: SS-01
phase: run
depends_on: []
---

### 1. Project scaffold, FastMCP server, and Finding schema
- **Scope:** Create the greenfield Python project (uv), a FastMCP stdio server that registers the tool surface as stubs, and the shared `Finding` model + a tier enum. Establish the adapter registration seam.
- **Files (new):**
  - `pyproject.toml`
  - `README.md`
  - `src/harrier/__init__.py`
  - `src/harrier/server.py`
  - `src/harrier/schema.py`
  - `tests/test_schema.py`
- **Decisions:** `server.py` exposes `register_all(app) -> None` that calls each module's `register(app: FastMCP) -> None`; the `Finding` model is a pydantic model matching the committed schema in the design doc.
- **Acceptance criteria:**
  - `[MECHANICAL]` `uv run python -c "import harrier.server"` exits 0.
  - `[STRUCTURAL]` `src/harrier/schema.py` defines a `Finding` pydantic model with fields `selector, source_tool, url, value, exists, confidence("high"|"medium"|"low"), tier("free"|"scrape"|"blocked"), reason, raw`.
  - `[STRUCTURAL]` `server.py` exposes `register_all(app) -> None` and a `main()` that starts a FastMCP stdio server.
  - `[MECHANICAL]` `uv run pytest tests/test_schema.py` passes.

---
sub_spec_id: SS-02
phase: run
depends_on: ['SS-01']
---

### 2. Candidate / permutation generator
- **Scope:** Implement `generate_candidates` producing ranked handle/email permutations from name parts, including maiden/married/nickname crosses, capped at `max`.
- **Files (new):**
  - `src/harrier/candidates.py`
  - `tests/test_candidates.py`
- **Files (modify):**
  - `src/harrier/server.py`
- **Decisions:** signature `generate_candidates(first, last, maiden=None, married=None, nicknames=[], max=25) -> list[str]`; patterns include `first.last, flast, firstl, f.last, firstlast, initials`, plus maiden/married and nickname crosses; ranked by likelihood.
- **Acceptance criteria:**
  - `[BEHAVIORAL]` `generate_candidates("amanda","bennett",maiden="wademan",married="warm")` returns a list including `amanda.wademan`, `awademan`, and `amandawarm`.
  - `[STRUCTURAL]` result length never exceeds `max`.
  - `[MECHANICAL]` `uv run pytest tests/test_candidates.py` passes.
  - `[STRUCTURAL]` `generate_candidates` is registered as an MCP tool via `register(app)`.

---
sub_spec_id: SS-03
phase: run
depends_on: ['SS-01']
---

### 3. Free tool adapters (username / email / phone / domain)
- **Scope:** Adapter per free tool, each normalizing to `Finding`. Import holehe/socialscan as libs; subprocess Sherlock/Maigret/theHarvester/PhoneInfoga. Missing tool → `status: unavailable`, never raise.
- **Files (new):**
  - `src/harrier/adapters/__init__.py`
  - `src/harrier/adapters/username.py`
  - `src/harrier/adapters/email.py`
  - `src/harrier/adapters/phone.py`
  - `src/harrier/adapters/domain.py`
  - `tests/test_adapters.py`
- **Files (modify):**
  - `src/harrier/server.py`
- **Decisions:** each adapter exposes `run(selector, **opts) -> list[Finding]` and a `status`; single-source hits get `confidence="low"`. (A-1) Sherlock has no stdout JSON — invoke via `subprocess` with `--folderoutput <tmp> --print-found --timeout 30` and parse the per-run result file (or Maigret `--json simple` to a temp file); default per-adapter timeout **30s**. (A-2) All subprocess calls pass args as a **list** (never `shell=True`); selectors are validated (reject shell metacharacters) before dispatch.
- **Acceptance criteria:**
  - `[STRUCTURAL]` each adapter module exposes `run(...) -> list[Finding]` returning the schema.
  - `[BEHAVIORAL]` with a tool binary absent, the adapter returns `status="unavailable"` and an empty finding list (no exception) — covered by a test that monkeypatches the binary path.
  - `[MECHANICAL]` `uv run pytest tests/test_adapters.py` passes.
  - `[STRUCTURAL]` `username_sweep`, `email_recon`, `phone_lookup`, `domain_harvest` are registered MCP tools.

---
sub_spec_id: SS-04
phase: run
depends_on: ['SS-01']
---

### 4. People-search browser module (validation spike + consent-gated adapter)
- **Scope:** FIRST a validation spike proving ≥1 free people-search site is reachable via Playwright; then a `people_search` adapter for that site, consent-gated, tier-tagging `scrape` on success and `blocked` (with reason) on 403/CAPTCHA. Rate-limited + jitter.
- **Files (new):**
  - `src/harrier/adapters/people_search.py`
  - `docs/ss04-spike-evidence.md`
  - `tests/test_people_search.py`
- **Files (modify):**
  - `src/harrier/server.py`
- **Decisions:** signature `people_search(name, city_or_state=None, age=None, consent=False) -> {findings, status}`; returns `status="blocked"` with `tier="blocked"` unless `consent=True`; on block, emit a `Finding` whose `reason` is the manual step. Target site chosen by the spike; stealth level starts plain, escalates only if needed.
- **Acceptance criteria:**
  - `[HUMAN REVIEW]` `docs/ss04-spike-evidence.md` records which site was tested and whether it was scrapable (the ASM-1 gate).
  - `[BEHAVIORAL]` `people_search(..., consent=False)` returns `status="blocked"` and performs no network call.
  - `[BEHAVIORAL]` on a simulated 403/CAPTCHA, the adapter returns a `blocked` Finding carrying a manual-step `reason` rather than raising.
  - `[MECHANICAL]` `uv run pytest tests/test_people_search.py` passes.

---
sub_spec_id: SS-05
phase: run
depends_on: ['SS-02', 'SS-03', 'SS-04']
---

### 5. Fan-out runner, correlator, and person_sweep orchestrator
- **Scope:** Concurrency-capped async runner that dispatches (candidate × adapter) jobs, a correlator that dedups and sets confidence by cross-source agreement (≥2 sources → high; single → low), and the `person_sweep` high-level tool wiring candidates → adapters → correlation. This is the integration seam.
- **Files (new):**
  - `src/harrier/runner.py`
  - `src/harrier/correlate.py`
  - `src/harrier/sweep.py`
  - `tests/test_sweep.py`
- **Files (modify):**
  - `src/harrier/server.py`
- **Decisions:** `person_sweep(name, city=None, state=None, maiden=None, nicknames=[], email=None, phone=None, permute=True, depth="quick", consent=False) -> {findings, sources, candidates}`; runner honors a global concurrency cap + jitter; `quick` vs `deep` sets the tool/candidate budget.
- **Acceptance criteria:**
  - `[INTEGRATION]` `person_sweep` invokes candidate generation then all registered adapters, and returns a merged result with `findings`, per-source `sources[]` status, and the `candidates[]` used — verified with adapters stubbed to return fixtures.
  - `[BEHAVIORAL]` a finding confirmed by two stubbed adapters is rated `confidence="high"`; a single-source finding is `"low"`.
  - `[STRUCTURAL]` the runner enforces a max-concurrency cap (configurable).
  - `[BEHAVIORAL]` (A-3) when every adapter reports `unavailable`, `person_sweep` returns an empty `findings` list with all `sources[]` marked `unavailable` — no exception raised.
  - `[MECHANICAL]` `uv run pytest tests/test_sweep.py` passes.

---
sub_spec_id: SS-06
phase: run
depends_on: ['SS-05']
dispatch: manual
---

### 6. `/osint` skill integration (flag, not new skill)
- **Note (C-1, red-team):** `dispatch: manual` — the `(modify)` targets live outside the `harrier` repo worktree (`~/.claude/skills/…`, `Software/OSINT/…`), so a factory worker cannot reach them. A human/operator applies this sub-spec after the MCP is built.
- **Scope:** Update the existing `/osint` skill to auto-detect the Harrier MCP in `--deep` mode and route collection through `person_sweep` in addition to web search, with a `--no-mcp` override and graceful web-only fallback when Harrier is absent. Document install/registration.
- **Files (modify):**
  - `~/.claude/skills/osint/SKILL.md`
  - `Software/OSINT/osint-skill/SKILL.md`
- **Files (new):**
  - `Software/OSINT/Harrier — Install & Register.md`
- **Decisions:** add a "MCP-augmented collection" section: if the `harrier` MCP tools are available, `--deep` calls `person_sweep` and folds tier-tagged findings into the dossier (scrape/blocked → §10 with confidence+source); `--no-mcp` forces web-only; absence of Harrier silently falls back.
- **Acceptance criteria:**
  - `[STRUCTURAL]` `~/.claude/skills/osint/SKILL.md` contains an MCP-augmented-collection section referencing `person_sweep`, `--no-mcp`, and graceful fallback.
  - `[STRUCTURAL]` `Software/OSINT/osint-skill/SKILL.md` mirror is updated identically.
  - `[STRUCTURAL]` `Harrier — Install & Register.md` documents `uv` install + Claude Code MCP registration steps.
  - `[HUMAN REVIEW]` a `--deep` run with Harrier registered folds `person_sweep` findings into the dossier with tiers and confidence.

---

## Edge Cases
- **All people-search sites blocked** → every people finding is `tier: blocked` with a manual step; sweep still returns username/email/domain results (never silent-empty).
- **Tool not installed** → adapter `status: unavailable`; sweep continues; `sources[]` reports it.
- **Permutation explosion** → capped by `max` candidates + per-tool site caps + `quick`/`deep` budget.
- **Sherlock false positives** → single-source = `low`; `high` requires ≥2 independent sources.
- **Oversized results** → cap per-tool hits, return top-N with a count note.
- **No consent** → `people_search`/scrape tier refuses and returns `blocked` without a network call.

## Out of Scope
- Paid APIs/keys (HIBP paid, DeHashed, people-data APIs); facial recognition (PimEyes); credentialed/logged-in collection; dark-web/paste dumps at rest; knowledge-graph/link-chart rendering; persistence DB; multi-target batch; the n8n path (parked); a new standalone skill.

## Constraints
**Musts:** free sources only; every finding tier-tagged; per-claim confidence by cross-source agreement; graceful degrade (never crash the sweep on one failure); consent gate on scrape tier; rate-limit + jitter.
**Must-Nots:** no paid tools; no credentials/logins; no reusing recovered creds; no embedded LLM agent; no unthrottled fan-out from the host IP; no `shell=True` / unsanitized selectors in subprocess calls (A-2); no persisting raw findings to disk by default.
**Preferences:** import tools as libs where possible, subprocess only where required; mirror FoundryMCP layout; prefer honest `blocked` over silent empty.
**Escalation Triggers:** ASM-1 spike shows no free people-search source scrapable; a tool requires paid/credentialed access; a committed contract must change.

## Verification
Build order SS-01 → (SS-02, SS-03, SS-04 in parallel) → SS-05 → SS-06. End-to-end: register Harrier, run the `/osint` skill `--deep` on a known target, and confirm `person_sweep` returns tier-tagged, confidence-rated findings that the skill folds into the dossier (blocked sources → §10 manual steps). The ASM-1 spike evidence (SS-04) gates whether the people-search value prop holds.

## Phase Specs

Refined by `/forge-prep` on 2026-07-10.

| Sub-Spec | Phase Spec |
|---|---|
| SS-01 Scaffold + server + Finding | `Harrier Phase Specs/sub-spec-1-scaffold.md` |
| SS-02 Candidate generator | `Harrier Phase Specs/sub-spec-2-candidates.md` |
| SS-03 Free tool adapters | `Harrier Phase Specs/sub-spec-3-adapters.md` |
| SS-04 People-search spike + adapter | `Harrier Phase Specs/sub-spec-4-people-search.md` |
| SS-05 Fan-out + correlate + person_sweep | `Harrier Phase Specs/sub-spec-5-sweep.md` |
| SS-06 /osint skill integration (manual) | `Harrier Phase Specs/sub-spec-6-skill-integration.md` |

Index: `Harrier Phase Specs/index.md`
