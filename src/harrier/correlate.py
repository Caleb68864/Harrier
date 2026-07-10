"""Correlator (SS-05): dedup + cross-source confidence.

Confidence is earned by agreement, never assumed:
  * A claim confirmed by **≥2 independent source tools** → ``confidence="high"``.
  * A single-source claim → ``confidence="low"``.

Findings are grouped by a normalized key (value, else URL). Within a group we
keep one representative per source tool (dropping exact intra-tool duplicates)
and stamp every survivor with the group's confidence. ``blocked`` findings are
passed through untouched — a manual step is not a confirmed claim.
"""

from __future__ import annotations

from collections import defaultdict

from harrier.schema import Finding


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
        sources = {f.source_tool for f in group}
        confidence = "high" if len(sources) >= 2 else "low"
        seen_sources: set[str] = set()
        for f in group:
            if f.source_tool in seen_sources:
                continue  # drop exact intra-tool duplicate
            seen_sources.add(f.source_tool)
            f.confidence = confidence
            out.append(f)

    out.extend(passthrough)
    return out
