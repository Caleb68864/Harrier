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
    raw: dict[str, Any] = Field(default_factory=dict)
