"""`person_sweep` orchestrator (SS-05) — the integration seam.

Wires the whole pipeline: generate ranked candidates → fan them out across the
registered adapters under a concurrency cap → correlate for cross-source
confidence → return a merged, tier-tagged result plus a per-source status
report and the candidates used.

Graceful degradation is the contract: if every adapter is ``unavailable`` the
sweep returns an empty ``findings`` list with all ``sources[]`` marked
``unavailable`` — never an exception, never a silent-empty with no explanation.
"""

from __future__ import annotations

from typing import Any

from harrier import candidates as candidates_mod
from harrier.adapters import AdapterResult
from harrier.adapters import domain as domain_mod
from harrier.adapters import email as email_mod
from harrier.adapters import people_search as people_mod
from harrier.adapters import phone as phone_mod
from harrier.adapters import username as username_mod
from harrier.correlate import correlate
from harrier.runner import run_jobs_sync
from harrier.schema import Finding

# Candidate budget per depth level (keeps the fan-out bounded).
_BUDGET = {"quick": 8, "deep": 25}


def _split_name(name: str) -> tuple[str, str]:
    parts = (name or "").split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[-1]


def _normalize(tool: str, result: Any) -> tuple[str, str, list[Finding]]:
    """Coerce any adapter return into ``(tool, status, findings)``."""
    if isinstance(result, Exception):
        return tool, "error", []
    if isinstance(result, AdapterResult):
        return tool, result.status, list(result)
    if isinstance(result, dict):  # people_search shape
        return tool, result.get("status", "unknown"), list(result.get("findings", []))
    if isinstance(result, (list, tuple)):
        return tool, "ok", list(result)
    return tool, "unknown", []


def _merge_sources(rows: list[tuple[str, str, list[Finding]]]) -> list[dict]:
    """Aggregate per-tool status + finding counts for the ``sources[]`` report."""
    agg: dict[str, dict] = {}
    for tool, status, findings in rows:
        entry = agg.setdefault(tool, {"tool": tool, "status": status, "count": 0})
        entry["count"] += len(findings)
        # Prefer a positive/informative status if any job for the tool got one.
        rank = {"ok": 3, "empty": 2, "blocked": 1}
        if rank.get(status, 0) > rank.get(entry["status"], 0):
            entry["status"] = status
    return list(agg.values())


def person_sweep(
    name: str,
    city: str | None = None,
    state: str | None = None,
    maiden: str | None = None,
    nicknames: list[str] | None = None,
    email: str | None = None,
    phone: str | None = None,
    permute: bool = True,
    depth: str = "quick",
    consent: bool = False,
    max_concurrency: int = 5,
) -> dict:
    """Run a full multi-source sweep for a person.

    Returns ``{"findings": [Finding...], "sources": [{tool,status,count}...],
    "candidates": [str...]}``. Never raises.
    """
    nicknames = nicknames or []
    first, last = _split_name(name)
    budget = _BUDGET.get(depth, _BUDGET["quick"])

    # 1) Candidate permutations (usernames / email-locals).
    cands: list[str] = []
    if permute and first and last:
        cands = candidates_mod.generate_candidates(
            first, last, maiden=maiden, nicknames=nicknames, max=budget
        )

    # 2) Build the job list (tool, zero-arg callable).
    jobs: list[tuple[str, Any]] = []
    for c in cands:
        jobs.append(("username", (lambda c=c: username_mod.run(c))))
    if email:
        jobs.append(("email", (lambda: email_mod.run(email))))
        dom = email.split("@")[-1] if "@" in email else None
        if dom:
            jobs.append(("domain", (lambda d=dom: domain_mod.run(d))))
    if phone:
        jobs.append(("phone", (lambda: phone_mod.run(phone))))
    # People-search always participates (consent-gated inside the adapter).
    city_or_state = city or state
    jobs.append(
        ("people_search",
         (lambda: people_mod.run(name, city_or_state=city_or_state, consent=consent)))
    )

    # 3) Fan out under the concurrency cap + jitter.
    raw = run_jobs_sync(jobs, max_concurrency=max_concurrency)
    rows = [_normalize(tool, result) for tool, result in raw]

    # 4) Merge + correlate.
    all_findings: list[Finding] = []
    for _, _, findings in rows:
        all_findings.extend(findings)
    correlated = correlate(all_findings)
    sources = _merge_sources(rows)

    return {
        "findings": correlated,
        "sources": sources,
        "candidates": cands,
    }


def register(app) -> None:
    """Register the `person_sweep` MCP tool."""

    @app.tool(name="person_sweep")
    def person_sweep_tool(
        name: str,
        city: str | None = None,
        state: str | None = None,
        maiden: str | None = None,
        nicknames: list[str] | None = None,
        email: str | None = None,
        phone: str | None = None,
        permute: bool = True,
        depth: str = "quick",
        consent: bool = False,
    ) -> dict:
        """Fan a person out across free OSINT sources; return tier-tagged findings."""
        res = person_sweep(
            name, city=city, state=state, maiden=maiden, nicknames=nicknames,
            email=email, phone=phone, permute=permute, depth=depth, consent=consent,
        )
        return {
            "findings": [f.model_dump() for f in res["findings"]],
            "sources": res["sources"],
            "candidates": res["candidates"],
        }
