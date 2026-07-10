---
type: phase-spec-index
master_spec: "../Harrier — OSINT MCP Spec.md"
date: 2026-07-10
sub_specs: 6
---

# Harrier — OSINT MCP — Phase Specs

Refined from [[Harrier — OSINT MCP Spec]] by `/forge-prep` on 2026-07-10. Greenfield repo (`C:\Users\CalebBennett\Documents\GitHub\harrier`) — all files `(new)`, no existing patterns to follow; mirror `FoundryMCP` layout.

| Sub-Spec | Title | Wave | Deps | Dispatch | Phase Spec |
|---|---|---|---|---|---|
| SS-01 | Scaffold + FastMCP server + `Finding` | 1 | none | factory | [sub-spec-1-scaffold.md](sub-spec-1-scaffold.md) |
| SS-02 | Candidate/permutation generator | 2 | SS-01 | factory | [sub-spec-2-candidates.md](sub-spec-2-candidates.md) |
| SS-03 | Free tool adapters | 2 | SS-01 | factory | [sub-spec-3-adapters.md](sub-spec-3-adapters.md) |
| SS-04 | People-search spike + adapter | 2 | SS-01 | factory | [sub-spec-4-people-search.md](sub-spec-4-people-search.md) |
| SS-05 | Fan-out + correlate + `person_sweep` | 3 | SS-02,03,04 | factory | [sub-spec-5-sweep.md](sub-spec-5-sweep.md) |
| SS-06 | `/osint` skill flag integration | 4 | SS-05 | **manual** | [sub-spec-6-skill-integration.md](sub-spec-6-skill-integration.md) |

## Requirement Traceability Matrix
| Requirement | Covered By |
|---|---|
| R1 FastMCP server + tool surface | SS-01, SS-05 |
| R2 `Finding` schema | SS-01 |
| R3 permutation generator | SS-02 |
| R4 free tool adapters + graceful degrade | SS-03 |
| R5 people-search (consent-gated, spike) | SS-04 |
| R6 fan-out + correlate + `person_sweep` | SS-05 |
| R7 `/osint` flag integration | SS-06 |

No orphaned requirements. Integration is covered by SS-05 (`person_sweep` `[INTEGRATION]`) + SS-06 (skill wiring) — no separate integration sub-spec generated.

## Cross-Spec Dependency Audit
Producers precede consumers: SS-01 (`Finding`, `register` seam) → W1; SS-02/03/04 (candidates, adapters) → W2; SS-05 consumes all of W2 → W3; SS-06 consumes SS-05 → W4. No wave violations.

## Gate
**SS-04 ASM-1 spike is the value-prop gate.** If no free people-search source is scrapable, stop and re-brainstorm before relying on the people-search dimension (username/email/domain still work).

## Execution
Run `/forge-run "Software/OSINT/Harrier — OSINT MCP Spec.md"` to execute (point at the master spec; forge-run auto-detects these phase specs). SS-06 is `dispatch: manual` — apply by hand after the build.
