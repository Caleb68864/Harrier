"""Tests for handle-distinctiveness scoring (Phase 1)."""

from harrier.distinct import distinctiveness


def test_distinctive_maiden_handle_scores_high():
    # embedding a rare, anchor-derived surname is a strong signal
    assert distinctiveness("amandawademan", ["Bennett", "Wademan"]) >= 0.6
    assert distinctiveness("amanda.wademan", ["Bennett", "Wademan"]) >= 0.6


def test_common_handles_score_below_gate():
    # short / common-surname handles are near-worthless as identity evidence
    for h in ["ab", "abennett", "amandab", "amanda.bennett"]:
        assert distinctiveness(h, ["Bennett", "Wademan"]) < 0.5


def test_empty_handle_is_zero():
    assert distinctiveness("", ["Wademan"]) == 0.0


def test_no_distinctive_anchor_falls_back_to_length():
    # with no rare anchor token to match, even a long handle stays modest
    assert distinctiveness("amandawademan", None) < 0.6
    # a common surname in the anchor does NOT grant the boost
    assert distinctiveness("amandabennett", ["Bennett"]) < 0.5
