---
sub_spec_id: SS-06
phase: run
depends_on: ['SS-05']
dispatch: manual
wave: 4
---

# SS-06 — `/osint` skill flag integration (MANUAL)

> `dispatch: manual` — targets live OUTSIDE the `harrier` repo worktree (`~/.claude/skills/…`, `Software/OSINT/…`). A human/operator applies this after the MCP is built and registered. A factory worker cannot reach these paths.

## Provides
- `/osint --deep` auto-detects Harrier and routes collection through `person_sweep`; `--no-mcp` override; graceful web-only fallback.

## Requires
- SS-05 `person_sweep` (MCP registered).

## Manual Implementation Steps
1. Register `harrier-mcp` in Claude Code MCP config (stdio) on the machine.
2. Edit `~/.claude/skills/osint/SKILL.md` — add an **"MCP-augmented collection"** section: if the `harrier` tools are available, `--deep` calls `person_sweep(name, selectors, consent=…)` and folds tier-tagged findings into the dossier (scrape/blocked → §10 with confidence+source); `--no-mcp` forces web-only; absence → silent web-only fallback.
3. Mirror the same edit into `Software/OSINT/osint-skill/SKILL.md`.
4. Create `Software/OSINT/Harrier — Install & Register.md` (uv install + MCP registration steps).
5. Reload Claude Code; run `/osint "<known target>" --deep` and confirm `person_sweep` findings appear in the dossier with tiers + confidence.

## Verification
- `[STRUCTURAL]` both SKILL.md copies contain an MCP-augmented-collection section referencing `person_sweep`, `--no-mcp`, and fallback.
- `[STRUCTURAL]` `Harrier — Install & Register.md` exists with install + registration steps.
- `[HUMAN REVIEW]` a `--deep` run with Harrier registered folds `person_sweep` findings (tiered, confidence-rated) into the dossier.
