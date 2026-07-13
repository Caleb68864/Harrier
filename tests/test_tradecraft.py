"""Tests for the intelligence-tradecraft layer (ICD-203 + ICS 206-01)."""

from __future__ import annotations

import hashlib

from harrier.schema import Finding
from harrier.tradecraft import (
    content_hash,
    likelihood_for_verdict,
    stamp_all,
    stamp_provenance,
)


def test_content_hash_matches_sha256():
    assert content_hash("hello") == hashlib.sha256(b"hello").hexdigest()
    assert content_hash("") is None
    assert content_hash(None) is None


def test_stamp_provenance_fills_ledger():
    f = Finding(selector="awademan", source_tool="sherlock",
                url="https://github.com/awademan", value="https://github.com/awademan")
    stamp_provenance(f, collected_at="2026-07-13T00:00:00+00:00")
    p = f.provenance
    assert p is not None
    assert p.source_url == "https://github.com/awademan"
    assert p.method == "sherlock"
    assert p.collected_at == "2026-07-13T00:00:00+00:00"
    assert p.content_hash == content_hash("https://github.com/awademan")


def test_stamp_provenance_is_idempotent():
    f = Finding(selector="x", source_tool="sherlock", value="v")
    stamp_provenance(f, collected_at="2026-01-01T00:00:00+00:00")
    first = f.provenance
    stamp_provenance(f, collected_at="2099-01-01T00:00:00+00:00")  # must NOT overwrite
    assert f.provenance is first
    assert f.provenance.collected_at == "2026-01-01T00:00:00+00:00"


def test_stamp_all_stamps_every_finding():
    fs = [Finding(selector="a", source_tool="t", value="1"),
          Finding(selector="b", source_tool="t", value="2")]
    stamp_all(fs, collected_at="2026-07-13T00:00:00+00:00")
    assert all(f.provenance is not None for f in fs)


def test_likelihood_maps_verdicts_icd203():
    assert likelihood_for_verdict("corroborated", matched=2) == "very likely"
    assert likelihood_for_verdict("corroborated", matched=1) == "likely"
    assert likelihood_for_verdict("false_positive") == "very unlikely"
    assert likelihood_for_verdict("reachable_no_corroboration") == "unlikely"
    # honest abstention — we did not assess a likelihood
    assert likelihood_for_verdict("unverifiable") is None
    assert likelihood_for_verdict(None) is None


def test_likelihood_terms_are_schema_valid():
    """Every produced term must be an accepted schema Likelihood (no typos)."""
    f = Finding(selector="x", source_tool="sherlock", value="v")
    for verdict, m in [("corroborated", 2), ("corroborated", 1),
                       ("false_positive", 0), ("reachable_no_corroboration", 0)]:
        f.likelihood = likelihood_for_verdict(verdict, m)  # pydantic validates on assign? no
        # Construct to force validation of the Literal.
        Finding(selector="x", source_tool="t", likelihood=likelihood_for_verdict(verdict, m))
