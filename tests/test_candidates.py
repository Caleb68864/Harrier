"""Tests for the candidate / permutation generator (SS-02)."""

from harrier.candidates import generate_candidates


def test_maiden_married_crosses():
    """Name parts cross over last / maiden / married surnames."""
    out = generate_candidates("amanda", "bennett", maiden="wademan", married="warm")
    assert "amanda.wademan" in out  # first.maiden
    assert "awademan" in out  # f+maiden (flast pattern)
    assert "amandawarm" in out  # first+married (firstlast pattern)
    assert len(out) <= 25


def test_respects_max():
    """Result length never exceeds max, even with many surnames + nicknames."""
    out = generate_candidates(
        "amanda",
        "bennett",
        maiden="wademan",
        married="warm",
        nicknames=["mandy", "amy"],
        max=10,
    )
    assert len(out) <= 10
    assert len(out) == len(set(out))  # deduped


def test_basic_patterns_present():
    """The core username patterns appear for a simple first+last."""
    out = generate_candidates("amanda", "bennett", max=25)
    assert "amanda.bennett" in out  # first.last
    assert "abennett" in out  # flast
    assert "amandab" in out  # firstl
    assert "amandabennett" in out  # firstlast


def test_nickname_cross():
    """Nicknames are used as alternate first names."""
    out = generate_candidates("amanda", "bennett", nicknames=["mandy"], max=25)
    assert any("mandy" in c for c in out)


def test_case_normalized_and_deduped():
    """Mixed-case input is lowercased and duplicates removed."""
    out = generate_candidates("Amanda", "Bennett", max=25)
    assert all(c == c.lower() for c in out)
    assert len(out) == len(set(out))


def test_ordering_stable_and_ranked():
    """The primary first.last handle ranks ahead of digit variants."""
    out = generate_candidates("amanda", "bennett", max=25)
    assert out.index("amanda.bennett") < out.index("amandabennett1")
