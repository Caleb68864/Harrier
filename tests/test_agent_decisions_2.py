"""Agent decisions, second batch (roadmap O26, O30, O31; 2026-11-21)."""

import harrier.investigate as inv
from harrier.correlate import correlate
from harrier.schema import Finding


# --- O26: dedupe by what was searched, not only by the value -----------------

def _holehe(email):
    return Finding(selector=email, source_tool="holehe", value="instagram", exists=True)


def test_correlate_keeps_same_value_from_different_selectors():
    out = correlate([_holehe("a@example.com"), _holehe("b@example.com")])
    assert sorted(f.selector for f in out) == ["a@example.com", "b@example.com"]
    assert {f.confidence for f in out} == {"low"}  # one family: no agreement


def test_correlate_still_drops_a_true_duplicate():
    out = correlate([_holehe("a@example.com"), _holehe("a@example.com")])
    assert len(out) == 1


def test_correlate_agreement_across_families_is_unchanged():
    a = Finding(selector="awademan", source_tool="sherlock", url="https://x/a",
                value="https://x/a")
    b = Finding(selector="Amanda Wademan", source_tool="courtlistener",
                value="https://x/a")
    assert {f.confidence for f in correlate([a, b])} == {"high"}


def test_investigate_dedup_keys_on_selector():
    out = inv._dedup([_holehe("a@example.com"), _holehe("b@example.com"),
                      _holehe("b@example.com")])
    assert sorted(f.selector for f in out) == ["a@example.com", "b@example.com"]
