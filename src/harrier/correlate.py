"""Correlator (SS-05): dedup + cross-source confidence.

Confidence is earned by agreement, never assumed:
  * A claim confirmed by **≥2 independent evidence families** →
    ``confidence="high"``.
  * A single-family claim → ``confidence="low"``.

Tools that probe the same sites the same way are one family, not two:
sherlock and maigret both enumerate the same username sites, and holehe and
socialscan both probe the same sites' sign-up/reset endpoints for an email.
Their agreement repeats one observation, so it doesn't earn ``high``. Any
other tool is its own family.

Findings are grouped by a normalized key (value, else URL). Within a group we
keep one representative per (source tool, selector), dropping exact intra-tool duplicates,
and stamp every survivor with the group's confidence. ``blocked`` findings are
passed through untouched — a manual step is not a confirmed claim.
"""

from __future__ import annotations

from collections import defaultdict

from harrier.schema import Finding


# Tools that observe the same thing the same way (see module docstring).
EVIDENCE_FAMILY = {
    "sherlock": "username-enumeration",
    "maigret": "username-enumeration",
    "holehe": "email-registration",
    "socialscan": "email-registration",
}


def evidence_family(tool: str) -> str:
    return EVIDENCE_FAMILY.get(tool, tool)


def _key(f: Finding) -> str:
    """Normalized identity for agreement grouping."""
    return (f.value or f.url or "").strip().lower()


def correlate(findings: list[Finding]) -> list[Finding]:
    """Dedup findings and set confidence by cross-source agreement."""
    passthrough: list[Finding] = []
    groups: dict[str, list[Finding]] = defaultdict(list)

    for f in findings:
        # Blocked / keyless findings aren't correlatable claims — pass through.
        if f.tier == "blocked" or not _key(f):
            passthrough.append(f)
            continue
        groups[_key(f)].append(f)

    out: list[Finding] = []
    for group in groups.values():
        families = {evidence_family(f.source_tool) for f in group}
        confidence = "high" if len(families) >= 2 else "low"
        # Decided by agent 2026-11-21 (roadmap O26): a duplicate is the same
        # tool AND the same searched selector. Two emails both registered on
        # one site (holehe value = site name) are two findings, not one.
        seen_sources: set[tuple[str, str]] = set()
        for f in group:
            dup_key = (f.source_tool, (f.selector or "").strip().lower())
            if dup_key in seen_sources:
                continue  # drop exact intra-tool duplicate
            seen_sources.add(dup_key)
            f.confidence = confidence
            out.append(f)

    out.extend(passthrough)
    return out
