# Harrier — OSINT MCP

A Python/FastMCP server that gives the `/osint` Claude Code skill real collection power: it wraps free OSINT tools (Sherlock, Maigret, holehe, socialscan, theHarvester, PhoneInfoga), adds a **name/username permutation fan-out engine**, and reaches the free people-search layer via a headless browser — returning normalized, tier-tagged, confidence-rated findings.

Free sources only. Consent-gated scraping. See `docs/specs/harrier-osint-mcp.md` for the full spec and `docs/specs/harrier-osint-mcp/` for phase specs.

## Status
Spec'd and ready to build (via Forge dark factory). Not yet implemented.

**Build gate:** SS-04 is an ASM-1 validation spike — prove ≥1 free people-search site is scrapable via Playwright before relying on the people-search dimension.

## Build
```
# from this repo root, in a Claude Code session:
/forge-dark-factory docs/specs/harrier-osint-mcp.md
```

## Legal / ethics
Public sources only; no paid APIs; no credentials/logins. Findings are read-only context — never a basis for an employment/insurance/tenant/credit decision (FCRA). The scrape tier is ToS-sensitive and consent-gated.
