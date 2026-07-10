"""Tests for the shared Finding schema (SS-01)."""

import pytest
from pydantic import ValidationError

from harrier.schema import Finding


def test_finding_defaults():
    """A Finding built with only required fields gets sane defaults."""
    f = Finding(selector="amanda.bennett", source_tool="sherlock")
    assert f.selector == "amanda.bennett"
    assert f.source_tool == "sherlock"
    # Sensible defaults for optional context.
    assert f.url is None
    assert f.value is None
    assert f.exists is None
    assert f.reason is None
    assert f.raw == {}
    # Single-source hits are low confidence until the correlator upgrades them.
    assert f.confidence == "low"
    assert f.tier == "free"


def test_finding_rejects_bad_tier():
    """tier only accepts the committed enum values."""
    with pytest.raises(ValidationError):
        Finding(selector="x", source_tool="t", tier="premium")


def test_finding_rejects_bad_confidence():
    """confidence only accepts the committed enum values."""
    with pytest.raises(ValidationError):
        Finding(selector="x", source_tool="t", confidence="certain")


def test_finding_full_roundtrip():
    """All fields populate and survive a model dump."""
    f = Finding(
        selector="amanda@example.com",
        source_tool="holehe",
        url="https://example.com/amanda",
        value="registered",
        exists=True,
        confidence="high",
        tier="free",
        reason=None,
        raw={"raw_key": "raw_val"},
    )
    dumped = f.model_dump()
    assert dumped["exists"] is True
    assert dumped["tier"] == "free"
    assert dumped["raw"] == {"raw_key": "raw_val"}
