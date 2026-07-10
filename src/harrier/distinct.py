"""Handle-distinctiveness scoring (Phase 1 — false-positive reduction).

Username enumeration confirms a handle is TAKEN, not WHOSE it is. A hit on a
common handle (``ab``, ``abennett``) is near-zero identity evidence; a hit on a
rare, anchor-derived handle (``amandawademan``) is a real lead. This scores that
prior so ``person_sweep`` can surface distinctive leads and suppress generic
existence-only noise before any (future) profile verification spends effort.

Score in [0, 1]:
  * empty / very short handles collide with everyone -> ~0
  * a handle embedding a *distinctive* anchor surname (>=6 chars and not a
    top-common surname) -> strong boost; that token is unlikely to be coincidence
  * otherwise a mild length nudge (longer = slightly less collision-prone)
"""

from __future__ import annotations

# A small stop-list of very common US/English surnames. Not exhaustive — it only
# needs to stop the "distinctive token" boost from firing on ordinary names, so
# that e.g. `abennett` (common surname) stays low while `amandawademan` (rare)
# scores high.
COMMON_SURNAMES = {
    "smith", "johnson", "williams", "brown", "jones", "garcia", "miller",
    "davis", "rodriguez", "martinez", "hernandez", "lopez", "gonzalez", "wilson",
    "anderson", "thomas", "taylor", "moore", "jackson", "martin", "lee",
    "thompson", "white", "harris", "clark", "lewis", "robinson", "walker",
    "young", "allen", "king", "wright", "scott", "green", "baker", "adams",
    "nelson", "hill", "campbell", "mitchell", "roberts", "carter", "phillips",
    "evans", "turner", "parker", "collins", "edwards", "stewart", "morris",
    "murphy", "cook", "rogers", "cooper", "peterson", "bailey", "reed", "kelly",
    "howard", "cox", "ward", "richardson", "watson", "brooks", "wood", "james",
    "bennett", "gray", "hughes", "price", "myers", "long", "foster", "sanders",
    "ross", "morgan", "reyes", "bell", "murray", "ford", "hamilton", "graham",
}

_MIN_DISTINCT_LEN = 6


def _distinctive_tokens(surnames: list[str] | None) -> list[str]:
    """Anchor surnames rare enough that embedding one in a handle is a signal."""
    out: list[str] = []
    for s in surnames or []:
        s = (s or "").strip().lower()
        if len(s) >= _MIN_DISTINCT_LEN and s not in COMMON_SURNAMES:
            out.append(s)
    return out


def distinctiveness(handle: str, surnames: list[str] | None = None) -> float:
    """Score a handle's identity-distinctiveness in [0, 1] given anchor surnames."""
    h = "".join(ch for ch in (handle or "").lower() if ch.isalnum())
    n = len(h)
    if n == 0:
        return 0.0
    # Embedding a rare, anchor-derived surname is the strongest cheap signal.
    for tok in _distinctive_tokens(surnames):
        if tok in h:
            return min(1.0, 0.85 + min(0.1, (n - len(tok)) * 0.02))
    # Otherwise: short handles collide with everyone; longer ones a bit less so.
    if n <= 4:
        return 0.05
    if n <= 7:
        return 0.2
    if n <= 10:
        return 0.35
    return 0.45
