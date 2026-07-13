"""Shared normalization contract for all Harrier adapters.

Every adapter — username, email, phone, domain, people-search — normalizes its
raw output into a list of `Finding` objects. This is the single schema the
correlator and the `/osint` skill consume, so it is deliberately small and
stable.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Confidence = Literal["high", "medium", "low"]
Tier = Literal["free", "scrape", "blocked"]

# ICD-203 Words of Estimative Probability (WEP), low→high. This expresses the
# *likelihood a finding's claim is true* — kept DISTINCT from ``confidence``
# (the analyst's confidence in the assessment), per intelligence tradecraft. The
# server only sets this where it is deterministically earned (a verify verdict);
# it is never invented.
Likelihood = Literal[
    "almost no chance", "very unlikely", "unlikely", "roughly even chance",
    "likely", "very likely", "almost certain",
]


class Provenance(BaseModel):
    """ICS 206-01-shaped source ledger for a finding — where it came from and
    when, so a claim can be validated and cited rather than trusted.

      source_url   -- the source the finding was drawn from.
      collected_at -- ISO-8601 UTC timestamp of collection.
      method       -- how it was obtained (the tool / access method).
      content_hash -- sha256 of the evidence text, so the exact bytes behind the
                      claim are pinned (tamper-evidence / dedup).
    """

    source_url: Optional[str] = None
    collected_at: Optional[str] = None
    method: Optional[str] = None
    content_hash: Optional[str] = None


class Finding(BaseModel):
    """A single normalized OSINT finding.

    Fields:
      selector    -- the input that produced this (a candidate handle, email,
                     phone, or domain).
      source_tool -- which adapter/tool emitted it (e.g. "sherlock", "holehe").
      url         -- a URL for the hit, if any.
      value       -- the resolved value (profile URL, address line, etc.).
      exists      -- tri-state: True (confirmed), False (confirmed-absent),
                     None (unknown / not asserted).
      confidence  -- per-claim confidence; set by cross-source agreement in the
                     correlator. A single-source hit is "low".
      tier        -- access tier: "free" (public tool), "scrape" (headless
                     browser), "blocked" (refused / gated / CAPTCHA).
      reason      -- human-readable note; for blocked/unavailable findings this
                     carries the manual step or the cause.
      distinctiveness -- [0,1] prior on how identity-bearing the selector is
                     (set for username existence hits): a rare anchor-derived
                     handle scores high, a common handle near zero. Used to
                     surface leads and suppress noise. None when not scored.
      likelihood  -- ICD-203 estimative-probability of the claim being true
                     (distinct from ``confidence``). Set only where deterministically
                     earned (a verify verdict); None otherwise — never invented.
      provenance  -- ICS 206-01 source ledger (url / time / method / hash).
      raw         -- the untouched adapter payload for auditing (never persisted
                     to disk by default).
    """

    selector: str
    source_tool: str
    url: Optional[str] = None
    value: Optional[str] = None
    exists: Optional[bool] = None
    confidence: Confidence = "low"
    tier: Tier = "free"
    reason: Optional[str] = None
    distinctiveness: Optional[float] = None
    likelihood: Optional[Likelihood] = None
    provenance: Optional[Provenance] = None
    raw: dict[str, Any] = Field(default_factory=dict)
