"""Intelligence-tradecraft helpers — ICD-203 likelihood + ICS 206-01 provenance.

Two small, deterministic pieces that make Harrier output legible to an intel
consumer (and citable per the IC's 2024 OSINT standards):

  * :func:`stamp_provenance` — attach an ICS 206-01 source ledger (source URL,
    UTC collection time, method, sha256 of the evidence) to a finding.
  * :func:`likelihood_for_verdict` — map a DETERMINISTIC verify verdict to an
    ICD-203 Word of Estimative Probability. The server never invents a
    likelihood; it only expresses one the verification stage actually earned.

No probabilistic judgment lives here — these are lookups and hashes.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Optional

from harrier.schema import Finding, Provenance


def utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string (seconds precision, ``Z``)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def content_hash(text: str | None) -> Optional[str]:
    """sha256 hex of the evidence text, or None if there's nothing to hash."""
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def stamp_provenance(finding: Finding, method: str | None = None,
                     collected_at: str | None = None) -> Finding:
    """Attach an ICS 206-01 provenance ledger to ``finding`` (mutates + returns).

    Idempotent-ish: an existing provenance is left untouched so an earlier, more
    specific stamp (e.g. one carrying the exact fetched bytes) wins over a later
    blanket pass. ``collected_at`` is injectable for deterministic tests.
    """
    if finding.provenance is not None:
        return finding
    evidence = finding.value or finding.url or finding.selector
    finding.provenance = Provenance(
        source_url=finding.url,
        collected_at=collected_at or utc_now_iso(),
        method=method or finding.source_tool,
        content_hash=content_hash(evidence),
    )
    return finding


def stamp_all(findings: list[Finding], collected_at: str | None = None) -> list[Finding]:
    """Stamp provenance on every finding that lacks one. Returns the same list."""
    for f in findings:
        stamp_provenance(f, collected_at=collected_at)
    return findings


# Verify verdict → ICD-203 estimative probability. Deterministic lookup only.
def likelihood_for_verdict(verdict: str | None, matched: int = 0) -> Optional[str]:
    """Map a deterministic verify verdict to an ICD-203 WEP term (or None).

    ``unverifiable`` and unknown verdicts return None — we did not assess a
    likelihood, so we assert none (honest abstention, not "roughly even").
    """
    if verdict == "corroborated":
        return "very likely" if matched >= 2 else "likely"
    if verdict == "false_positive":
        return "very unlikely"
    if verdict == "reachable_no_corroboration":
        return "unlikely"
    return None
