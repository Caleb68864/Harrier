"""Candidate / permutation generator (SS-02).

Expands a person's name parts into a ranked list of handle/email-local
candidates. Handles cross the first name (and nicknames) over every known
surname (last / maiden / married), which is the whole point: an `amanda bennett`
who was `wademan` and married into `warm` should surface `amanda.wademan` and
`amandawarm`, not just `amanda.bennett`.

Ranking is likelihood-ordered: the most common real-world handle shapes come
first, base (no-digit) patterns come before digit-suffixed variants, and the
primary surname is preferred over maiden/married. The list is deduped and
truncated to `max`.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

# Common trailing digits people append to handles. Kept short on purpose — this
# is a fan-out budget, not a brute force.
_DIGITS = ["1", "12", "123"]


def _clean(part: str | None) -> str | None:
    """Lowercase and strip a name part; drop empties/whitespace-only."""
    if not part:
        return None
    part = "".join(ch for ch in part.strip().lower() if ch.isalnum())
    return part or None


def _base_patterns(fn: str, sn: str) -> list[str]:
    """Likelihood-ordered handle shapes for one (first, surname) pair."""
    fi = fn[0]
    si = sn[0]
    return [
        f"{fn}.{sn}",   # first.last   — most common professional handle
        f"{fn}{sn}",    # firstlast
        f"{fi}{sn}",    # flast
        f"{fn}{si}",    # firstl
        f"{fi}.{sn}",   # f.last
        f"{fi}{si}",    # initials
    ]


def generate_candidates(
    first: str,
    last: str,
    maiden: str | None = None,
    married: str | None = None,
    nicknames: list[str] | None = None,
    max: int = 25,
) -> list[str]:
    """Generate ranked handle/email-local candidates from name parts.

    Args:
        first: given name (required).
        last: primary surname (required).
        maiden: maiden surname, if known.
        married: married surname, if known.
        nicknames: alternate given names (e.g. "mandy").
        max: hard cap on returned candidates.

    Returns:
        A ranked, deduped list of lowercase candidate strings, length <= max.
    """
    first = _clean(first)
    last = _clean(last)
    if not first or not last:
        return []

    # Alternate first names: the given name plus any nicknames.
    firsts = [first]
    for nick in nicknames or []:
        c = _clean(nick)
        if c and c not in firsts:
            firsts.append(c)

    # Surnames in preference order: primary last, then married, then maiden.
    surnames: list[str] = []
    for sn in (last, married, maiden):
        c = _clean(sn)
        if c and c not in surnames:
            surnames.append(c)

    ranked: list[str] = []

    # Pass 1: base patterns. Iterate first-major then surname-major so the
    # primary name/surname combos rank ahead of nickname/maiden/married combos.
    for fn in firsts:
        for sn in surnames:
            ranked.extend(_base_patterns(fn, sn))

    # Pass 2: first-name-only handles (some people use just their given name).
    ranked.extend(firsts)

    # Pass 3: digit-suffixed variants of the strongest concatenated shapes.
    for fn in firsts:
        for sn in surnames:
            for d in _DIGITS:
                ranked.append(f"{fn}{sn}{d}")
    for fn in firsts:
        for d in _DIGITS:
            ranked.append(f"{fn}{d}")

    # Dedup preserving rank order, then truncate to the budget.
    seen: set[str] = set()
    out: list[str] = []
    for c in ranked:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
        if len(out) >= max:
            break
    return out


def register(app: FastMCP) -> None:
    """Register `generate_candidates` as an MCP tool."""

    @app.tool(name="generate_candidates")
    def generate_candidates_tool(
        first: str,
        last: str,
        maiden: str | None = None,
        married: str | None = None,
        nicknames: list[str] | None = None,
        max: int = 25,
    ) -> list[str]:
        """Generate ranked handle/email candidates from a person's name parts."""
        return generate_candidates(
            first,
            last,
            maiden=maiden,
            married=married,
            nicknames=nicknames or [],
            max=max,
        )
