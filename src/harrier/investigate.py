"""Investigation loop — bounded plan→collect→verify→refine (the CoAnalyst360 shape).

A repeatable, DETERMINISTIC investigative workflow over Harrier's tools — this is
the "skills → repeatable workflows" half of CoAnalyst360. The agentic reasoning
(decomposing a plain-language objective, adjudicating matches, deciding what to
chase, writing the narrative) stays in the /osint skill: the LLM + the analyst.
That split is deliberate — no probabilistic judgment inside the deterministic MCP.

Each round:
  1. COLLECT  — person_sweep(verify=True) + court_search on the current anchor.
  2. VERIFY   — person_sweep already fetches/renders and corroborates; the
                verification verdicts ride on each finding.
  3. REFINE   — mine corroborated findings' extracted METADATA (Maigret `ids`)
                for a NEW distinctive surname not already in the anchor; if one
                appears, run another round with it folded in.
  4. SYNTHESIZE — merge + dedup across rounds; assemble next-steps (manual-assist
                links + unverified/gated leads). Bounded by ``max_rounds``.

Refinement only fires when real new metadata surfaces (rare for a private person)
— the engine is honest about finding nothing new and stopping.
"""

from __future__ import annotations

import re

from harrier import assist
from harrier import sweep as sweep_mod
from harrier import tradecraft
from harrier.adapters import court as court_mod
from harrier.distinct import COMMON_SURNAMES
from harrier.schema import Finding


def _known_tokens(name: str, state: str | None, city: str | None,
                  maiden: str | None, married: str | None,
                  nicknames: list[str]) -> set[str]:
    toks: set[str] = set()
    for chunk in [name, state or "", city or "", maiden or "", married or "",
                  *nicknames]:
        for w in re.findall(r"[a-z]{2,}", (chunk or "").lower()):
            toks.add(w)
    return toks


def _discovered_tokens(findings: list[Finding], known: set[str]) -> set[str]:
    """New distinctive surnames from corroborated findings' extracted metadata."""
    out: set[str] = set()
    for f in findings:
        ids = (f.raw or {}).get("ids")
        if not isinstance(ids, dict):
            continue
        for v in ids.values():
            for w in re.findall(r"[a-z]{6,}", str(v).lower()):
                if w not in known and w not in COMMON_SURNAMES:
                    out.add(w)
    return out


def _dedup(findings: list[Finding]) -> list[Finding]:
    seen: set[tuple] = set()
    out: list[Finding] = []
    # corroborated first, then by confidence, so the representative kept is best
    rank = {"high": 0, "medium": 1, "low": 2}
    for f in sorted(findings, key=lambda x: rank.get(x.confidence, 3)):
        key = (f.source_tool, (f.url or f.value or "").lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def _is_corroborated(f: Finding) -> bool:
    return (f.raw or {}).get("verify", {}).get("verdict") == "corroborated"


def investigate(
    name: str,
    city: str | None = None,
    state: str | None = None,
    maiden: str | None = None,
    married: str | None = None,
    nicknames: list[str] | None = None,
    email: str | None = None,
    phone: str | None = None,
    depth: str = "quick",
    engine: str = "sherlock",
    verify: bool = True,
    consent: bool = False,
    max_rounds: int = 2,
) -> dict:
    """Run a bounded plan→collect→verify→refine investigation. Never raises."""
    nicknames = list(nicknames or [])
    known = _known_tokens(name, state, city, maiden, married, nicknames)
    all_findings: list[Finding] = []
    tool_calls: list[str] = []
    discovered: list[str] = []
    rounds_run = 0

    for _ in range(max(1, max_rounds)):
        rounds_run += 1
        # 1-2) COLLECT + VERIFY
        sweep = sweep_mod.person_sweep(
            name, city=city, state=state, maiden=maiden, married=married,
            nicknames=nicknames, email=email, phone=phone, depth=depth,
            engine=engine, verify=verify, consent=consent,
        )
        tool_calls.append(f"person_sweep(engine={engine},verify={verify})")
        all_findings.extend(sweep["findings"])

        court = court_mod.run(name, state=state)
        tool_calls.append("court_search")
        all_findings.extend(list(court))

        # 3) REFINE — new distinctive surname in corroborated metadata?
        corroborated = [f for f in sweep["findings"] if _is_corroborated(f)]
        fresh = sorted(_discovered_tokens(corroborated, known))
        if not fresh or rounds_run >= max_rounds:
            break
        discovered.extend(fresh)
        known.update(fresh)
        nicknames.extend(fresh)  # fold the discovery into the next round's anchor

    # 4) SYNTHESIZE
    findings = _dedup(all_findings)
    tradecraft.stamp_all(findings)  # ICS 206-01 ledger on court + any unstamped
    corroborated = [f for f in findings if _is_corroborated(f)]

    next_steps: list[str] = []
    for f in findings:
        verdict = (f.raw or {}).get("verify", {}).get("verdict")
        if f.tier == "blocked" and f.reason:
            next_steps.append(f"Manual: {f.reason}")
        elif verdict in ("unverifiable", "reachable_no_corroboration") and f.url:
            next_steps.append(f"Verify by hand: {f.url}")

    return {
        "target": name,
        "rounds_run": rounds_run,
        "tool_calls": tool_calls,
        "discovered": discovered,
        "findings": findings,
        "corroborated": corroborated,
        "next_steps": next_steps[:20],
        "manual_assist": assist.manual_assist_links(
            name, city=city, state=state, maiden=maiden, married=married),
    }


def register(app) -> None:
    """Register the `investigate` MCP tool."""

    @app.tool(name="investigate")
    def investigate_tool(
        name: str,
        city: str | None = None,
        state: str | None = None,
        maiden: str | None = None,
        married: str | None = None,
        nicknames: list[str] | None = None,
        email: str | None = None,
        phone: str | None = None,
        depth: str = "quick",
        engine: str = "sherlock",
        verify: bool = True,
        consent: bool = False,
        max_rounds: int = 2,
    ) -> dict:
        """Bounded plan→collect→verify→refine investigation over all Harrier tools."""
        res = investigate(
            name, city=city, state=state, maiden=maiden, married=married,
            nicknames=nicknames, email=email, phone=phone, depth=depth,
            engine=engine, verify=verify, consent=consent, max_rounds=max_rounds,
        )
        return {
            "target": res["target"],
            "rounds_run": res["rounds_run"],
            "tool_calls": res["tool_calls"],
            "discovered": res["discovered"],
            "findings": [f.model_dump() for f in res["findings"]],
            "corroborated": [f.model_dump() for f in res["corroborated"]],
            "next_steps": res["next_steps"],
            "manual_assist": res["manual_assist"],
        }
