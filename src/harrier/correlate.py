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
keep one representative per source tool (dropping exact intra-tool duplicates)
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
        seen_sources: set[str] = set()
        for f in group:
            if f.source_tool in seen_sources:
                continue  # drop exact intra-tool duplicate
            seen_sources.add(f.source_tool)
            f.confidence = confidence
            out.append(f)

    out.extend(passthrough)
    return out
