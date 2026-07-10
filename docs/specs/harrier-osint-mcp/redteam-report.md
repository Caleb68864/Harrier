---
type: redteam-report
generated: 2026-07-10
target: "Harrier — OSINT MCP Spec.md"
findings_count: 6
critical: 1
advisory: 5
---

# Red Team Review: Harrier — OSINT MCP Spec

9-role adversarial review + construction-site check. 6 findings; all patched into the spec.

## CRITICAL (1)
**C-1: SS-06 modifies files outside the repo worktree** (Integration Architect / construction-site)
- Location: SS-06 Files (modify) — `~/.claude/skills/osint/SKILL.md`, `Software/OSINT/osint-skill/SKILL.md`
- Issue: a factory worker runs in a `harrier` repo worktree from HEAD; these targets are outside it and unreachable.
- Fix applied: SS-06 marked `dispatch: manual` (human applies the skill edit post-build).

## ADVISORY (5)
**A-1: Sherlock has no stdout JSON** (Developer) — SS-03 pinned to file-based parsing (`--folderoutput --print-found`) / Maigret `--json` to temp; committed.
**A-2: subprocess injection surface** (Security) — Must-Not added: args as list, no `shell=True`, selector validation; noted in SS-03.
**A-3: all-adapters-unavailable path** (QA) — added `[BEHAVIORAL]` AC to SS-05: empty findings + `unavailable` sources, no crash.
**A-4: no committed timeout** (SRE) — default 30s per-adapter timeout committed in SS-03.
**A-5: SS-03 bundles 4 adapters** (Scope Realist, YELLOW) — acceptable for MVP; `/forge-prep` may split into per-adapter phase steps.

## Role Scorecards
Developer: 1 | QA: 1 | End User: 0 | Architect: 1 | Scope Realist: 1 | Security: 1 | SRE: 1 | Data: 0 | Product: 0

## Result
1 CRITICAL + 5 ADVISORY, all auto-patched into `Harrier — OSINT MCP Spec.md`. Spec is execution-ready pending the SS-04 ASM-1 spike gate.
