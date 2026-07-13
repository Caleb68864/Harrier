# Harrier

**A disciplined free-source OSINT collection server for LLM agents.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-92%20passing-brightgreen.svg)](#testing)
[![Protocol](https://img.shields.io/badge/MCP-FastMCP%20stdio-8A2BE2.svg)](#registering-with-claude-code)
[![License](https://img.shields.io/badge/license-MIT-lightgrey.svg)](#license)

Harrier is a Python / [FastMCP](https://modelcontextprotocol.io) server that gives an LLM agent — the `/osint` Claude Code skill — real, disciplined OSINT collection power over **free, public sources**. It wraps a fleet of well-known open-source reconnaissance tools behind one normalized contract and returns **tier-tagged, confidence-rated, distinctiveness-scored findings** instead of a pile of raw tool output. The server collects; it does not judge. Adjudication is left to the analyst and the LLM, and the human is the final gate.

---

## Table of contents

- [Why Harrier](#why-harrier)
- [Design philosophy](#design-philosophy)
- [Architecture](#architecture)
- [The `investigate` loop](#the-investigate-loop)
- [MCP tools](#mcp-tools)
- [Free tools wrapped](#free-tools-wrapped)
- [Install & run](#install--run)
- [Registering with Claude Code](#registering-with-claude-code)
- [Usage example](#usage-example)
- [Legal & ethics](#legal--ethics)
- [Project layout](#project-layout)
- [Engineering quality](#engineering-quality)
- [Testing](#testing)
- [License](#license)

---

## Why Harrier

An LLM is a capable analyst but a poor scraper: it hallucinates URLs, cannot run `sherlock`, and has no disciplined way to tell a real lead from a coincidence. Point-and-shoot OSINT tools are the inverse — they enumerate aggressively but have no notion of *whose* account a taken handle is, and they crash the moment a binary is missing or the network hiccups.

Harrier is the connective tissue. It exposes free reconnaissance tooling to an agent through a single stable schema, layers deterministic reasoning on top (correlation, distinctiveness, verification), and refuses to make the probabilistic identity call that belongs to a human. The result is collection an analyst can trust and audit.

---

## Design philosophy

> **Harrier COLLECTS deterministically. The analyst / LLM ADJUDICATES. The human is the final gate.**

There is **no probabilistic judgment inside the server**. Every stage — permutation, correlation, distinctiveness, verification — is deterministic and explainable. The "is this the same person?" call stays outside the tool, with the `/osint` skill and the operator.

This split drives every other decision:

| Principle | What it means in the code |
|-----------|---------------------------|
| **Public sources only** | No logins, no paywalls, no purchased data-broker APIs. Everything wrapped is free and open. |
| **Consent-gated scraping** | The ToS-sensitive people-search scrape tier does nothing unless the caller passes `consent=True`. |
| **No anti-bot / Cloudflare bypass — by design** | Harrier never defeats a bot challenge. Where a wall stands, it emits **pre-filled manual-assist deep links** so the analyst's *real* browser crosses a wall the tool won't touch. Actively bypassing a challenge strengthens a ToS-circumvention claim; handing a human a link does not. |
| **FCRA boundary** | Findings are read-only context, never a basis for an employment, tenant, insurance, or credit decision. This is stated in the schema, the tools, and here. |
| **Graceful degradation contract** | A missing binary, missing import, bad selector, timeout, or network failure **never raises into the sweep**. It degrades to an honest `unavailable` / `blocked` / `timeout` status *with a reason* — never a crash, never a silent empty. |

---

## Architecture

Harrier is built from small, uniform pieces that compose into one orchestrated sweep.

### The adapter pattern

One module per tool. Every adapter exposes the same shape:

```python
def run(selector, **opts) -> AdapterResult:  # a list[Finding] that also carries .status
    ...
```

`AdapterResult` subclasses `list`, so callers iterate it as findings while still reading `.status` and `.reason`. The cardinal rule: an adapter degrades, it does not raise.

### The normalized `Finding` schema

Every adapter, from Sherlock to CourtListener, normalizes into one Pydantic model:

| Field | Meaning |
|-------|---------|
| `selector` | the input that produced this finding (a candidate handle, email, phone, domain) |
| `source_tool` | which adapter emitted it (`sherlock`, `holehe`, …) |
| `url` / `value` | the hit's URL and resolved value |
| `exists` | **tri-state**: `True` (confirmed), `False` (confirmed-absent), `None` (unknown / not asserted) |
| `confidence` | `high` / `medium` / `low` — set by cross-source agreement, not guessed |
| `tier` | access tier: `free` (public tool), `scrape` (headless browser), `blocked` (refused / gated / CAPTCHA) |
| `reason` | human-readable note; for blocked findings, the manual step or cause |
| `distinctiveness` | `[0,1]` prior on how identity-bearing the selector is |
| `raw` | the untouched adapter payload, for auditing |

### The concurrency-capped async runner

Adapters are blocking (subprocess / requests / Playwright), so each job runs in a worker thread via `asyncio.to_thread`, gated by a semaphore that caps concurrent outbound connections from the host IP. A small random jitter before each job spreads requests out for politeness. One job's failure comes back as the exception object — it never escapes the runner.

### Cross-source correlation

**Confidence is earned, never assumed.** Findings are grouped by a normalized key; a claim confirmed by **≥2 independent source tools** is promoted to `high`, a single-source claim stays `low`. Intra-tool duplicates are dropped; `blocked` findings pass through untouched (a manual step is not a confirmed claim).

### Distinctiveness scoring

Username enumeration proves a handle is **taken**, not **whose** it is. A hit on `abennett` is near-zero identity evidence; a hit on `amandawademan` (an anchor-derived maiden-name handle) is a real lead. Harrier scores that prior in `[0,1]`: handles embedding a rare, anchor-derived surname score high; common or very short handles score near zero and are **suppressed as noise** (surfaced only as a count, so nothing vanishes silently). A distinctive existence hit is capped at `medium` — an unverified lead — never `high`.

### The permutation / candidate engine

The engine crosses the first name (plus nicknames) over **every** known surname — last, maiden, and married — because that is the whole point of the maiden-name case: an `amanda bennett` who was `wademan` and married into `warm` should surface `amanda.wademan` and `amandawarm`, not just `amanda.bennett`. Candidates are ranked by real-world handle-shape likelihood, then re-ranked by distinctiveness so rare identity-bearing handles are actually swept rather than truncated behind common shapes.

### The verification stage

Enumeration false-positives are the enemy. The verification stage fetches a surfaced profile and scores it against the anchor — deterministically:

- **dead / 404 / soft-404** page → the enumeration hit was a false positive (`exists=False`).
- page text corroborates a **distinctive** anchor token (a maiden surname, an uncommon location) as a **standalone word** → promote confidence.
- reachable but no corroboration → left as an unverified lead.
- fetch blocked or a JS shell → retry with an optional **Playwright render** (a real headless browser that executes JS); only if *that* still can't read it is the finding left `unverifiable` ("confirm manually").

**Word-boundary matching** means a handle never self-corroborates: the profile page for `amandawademan` contains that concatenated handle, but `\bwademan\b` only matches a *standalone* "wademan" — a real display name — not the handle echo.

---

## The `investigate` loop

`investigate` is a bounded, deterministic **plan → collect → verify → refine → synthesize** workflow (the "CoAnalyst360 shape"). Each round:

1. **Collect** — `person_sweep(verify=True)` plus a `court_search` on the current anchor.
2. **Verify** — the sweep already fetches, renders, and corroborates; verdicts ride on each finding.
3. **Refine** — mine *corroborated* findings' extracted metadata (e.g. Maigret `ids`) for a **new distinctive surname** not already in the anchor. If one appears, fold it in and run another round.
4. **Synthesize** — merge and dedup across rounds; assemble next-steps (manual-assist links + unverified / gated leads).

The whole loop is bounded by `max_rounds`, and refinement only fires when genuinely new metadata surfaces — the engine is honest about finding nothing new and stopping. The agentic reasoning (decomposing the objective, adjudicating matches, writing the narrative) stays in the `/osint` skill; the deterministic MCP does not make that call.

---

## MCP tools

Harrier registers twelve tools through a one-line-per-tool registration seam in `server.py`:

| Tool | What it does |
|------|--------------|
| `person_sweep` | The orchestrator: permute a name → fan out across every adapter under a concurrency cap → correlate → gate by distinctiveness → optionally verify → return tier-tagged findings, a per-source status report, the candidates used, and manual-assist links. |
| `investigate` | The bounded plan→collect→verify→refine→synthesize loop over all Harrier tools. |
| `build_graph` | Turn correlated findings into a person-centered **entity graph** (nodes: accounts / emails / phones / cases / records; edges: provenance-stamped, distinctiveness-weighted) and export it as **GraphML** and **Neo4j Cypher** — the "map all connections" link-analysis artifact. |
| `username_sweep` | Enumerate a username across social sites via Sherlock (primary) with a Maigret fallback. |
| `email_recon` | Check whether an email is registered across free sources (holehe + socialscan). |
| `phone_lookup` | Scan a phone number with PhoneInfoga. |
| `domain_harvest` | Harvest emails / hosts / subdomains for a domain via theHarvester. |
| `people_search` | Reach the free people-search layer via a headless browser (consent-gated). |
| `court_search` | Search CourtListener / RECAP federal court records for a person by name. |
| `genealogy_search` | Search FamilySearch records — the free maiden-name resolver. |
| `generate_candidates` | Generate the ranked handle / email-local permutations from a person's name parts. |
| `manual_assist` | Build pre-filled deep links to walled / gated free sources (genealogy, obituaries, people-search, courts, records) — makes no network call, just constructs URLs. |

---

## Free tools wrapped

Harrier orchestrates these open-source reconnaissance tools and structured sources:

| Category | Tools / sources |
|----------|-----------------|
| Username enumeration | **Sherlock**, **Maigret** |
| Email recon | **holehe**, **socialscan** |
| Domain harvesting | **theHarvester** |
| Phone | **PhoneInfoga** |
| Structured, un-walled records | **CourtListener / RECAP**, **FamilySearch** |

Two sources accept an optional token for higher limits or record access:

| Env var | Effect |
|---------|--------|
| `COURTLISTENER_TOKEN` | raises the CourtListener API rate limit |
| `FAMILYSEARCH_ACCESS_TOKEN` | enables the FamilySearch record-search API |

Everything **degrades honestly** without them: no token means an `unavailable` status with a reason, not an error.

---

## Install & run

Harrier uses [`uv`](https://docs.astral.sh/uv/) and targets **Python 3.11+**.

```bash
# clone, then from the repo root:
uv sync                 # create the venv and install locked deps

# run the stdio MCP server directly:
uv run harrier-mcp
```

The wrapped CLI tools (Sherlock, Maigret, theHarvester, PhoneInfoga, …) are optional at runtime — any that are missing simply degrade to `unavailable`. Install the ones you want on `PATH` (or as Python deps) to light up those dimensions. For the Playwright render fallback, install browsers once with `uv run playwright install chromium`.

## Registering with Claude Code

Register Harrier as a user-scoped MCP server so the `/osint` skill can call it:

```bash
claude mcp add harrier --scope user -- uv run --directory <path-to-harrier-repo> harrier-mcp
```

`harrier-mcp` is the console entry point declared in `pyproject.toml` (`harrier-mcp = "harrier.server:main"`), which starts a FastMCP stdio server.

---

## Usage example

The `/osint` skill drives Harrier once it has a **confirmed anchor** (a real name plus any known city / state / maiden / married surnames). A typical call:

```jsonc
// person_sweep — a single disciplined multi-source sweep
{
  "name": "Amanda Bennett",
  "state": "NE",
  "maiden": "Wademan",
  "nicknames": ["Mandy"],
  "depth": "deep",
  "verify": true,
  "consent": false
}
```

…or the full loop:

```jsonc
// investigate — bounded plan→collect→verify→refine→synthesize
{ "name": "Amanda Bennett", "state": "NE", "maiden": "Wademan", "max_rounds": 2 }
```

Every finding comes back tier-tagged and confidence-rated, with a per-source status report and a set of manual-assist deep links for the walls the tool won't cross. **Findings are candidates to adjudicate, not facts.** The skill and the human decide identity; Harrier only collects the evidence and shows its work.

---

## Legal & ethics

Harrier is built for legitimate, lawful research — interview prep, B2B due diligence, trust-and-safety triage — over public information only.

- **Public sources only.** No logins, no paywalls, no purchased broker data.
- **Consent-gated scrape tier.** The ToS-sensitive people-search scrape does nothing without explicit `consent=True`.
- **No anti-bot bypass.** Walls are handed to a human as pre-filled links, never defeated by the tool.
- **FCRA read-only boundary.** Findings are context, **never** a basis for an employment, tenant, insurance, or credit decision.

You are responsible for using Harrier in compliance with the terms of service of the sources it touches and with applicable law in your jurisdiction.

---

## Project layout

```
harrier/
├── pyproject.toml            # uv project; harrier-mcp entry point
├── src/harrier/
│   ├── server.py             # FastMCP app + one-line-per-tool registration seam
│   ├── schema.py             # the normalized Finding contract (Pydantic)
│   ├── candidates.py         # name → ranked handle/email permutations
│   ├── distinct.py           # handle-distinctiveness scoring
│   ├── correlate.py          # cross-source confidence (≥2 tools → high)
│   ├── runner.py             # concurrency-capped async fan-out + loop-safe boundary
│   ├── sweep.py              # person_sweep orchestrator
│   ├── verify.py             # fetch + Playwright-render verification stage
│   ├── investigate.py        # bounded plan→collect→verify→refine loop
│   ├── graph.py              # build_graph entity graph + GraphML / Cypher export
│   ├── tradecraft.py         # ICD-203 likelihood + ICS 206-01 provenance ledger
│   ├── assist.py             # manual-assist pre-filled deep-link generator
│   └── adapters/             # one module per tool, uniform run() -> AdapterResult
│       ├── __init__.py       # AdapterResult, selector validation, safe subprocess
│       ├── username.py       # Sherlock + Maigret
│       ├── email.py          # holehe + socialscan
│       ├── phone.py          # PhoneInfoga
│       ├── domain.py         # theHarvester
│       ├── people_search.py  # headless-browser people-search (consent-gated)
│       ├── court.py          # CourtListener / RECAP
│       └── genealogy.py      # FamilySearch
└── tests/                    # 92 tests
```

---

## Engineering quality

- **~92 passing tests** covering the schema, every adapter, the runner, correlation, distinctiveness, verification, the sweep, the investigate loop, the tradecraft layer, and the entity graph.
- **Loop-safe sync ↔ async boundary.** FastMCP invokes sync tool bodies while its own event loop is running, which makes a bare `asyncio.run` and Playwright's sync API raise. `run_in_thread` / `run_coro_sync` are the single choke point that offloads to a worker thread only when a loop is actually running — so the server (and the render fallback) behave correctly live, not just in tests.
- **Selector validation** rejects shell metacharacters and path-traversal separators before any selector reaches a subprocess or a temp-file path; subprocesses always run with `shell=False` and list args.
- **Bounded, concurrent external calls** with a semaphore cap, per-job timeouts, and jitter.
- **Graceful degradation everywhere** — the sweep is contractually incapable of raising.

## Testing

```bash
uv run pytest          # 92 passing
uv run pytest -q       # quiet
```

---

## License

Released under the MIT License. See [`LICENSE`](LICENSE) for details.
