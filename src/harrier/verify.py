"""Profile verification stage (roadmap Phase 3b).

Enumeration only proves a handle is TAKEN. This stage fetches a surfaced
finding's profile URL and checks it against the target anchor, DETERMINISTICALLY
(the semantic "is this the same person?" judgment stays in the /osint skill):

  * dead / 404 / gone page → the enumeration hit was a FALSE POSITIVE: set
    ``exists=False``, drop confidence to "low", tag the reason. (This is the
    class the live Amanda run hit — Sherlock said the Spotify handle existed;
    fetching it returned 404.)
  * page text corroborates a DISTINCTIVE anchor token (maiden surname, an
    uncommon location) as a standalone word → promote confidence + record which
    fields matched.
  * page reachable but no corroboration → left as an unverified lead.
  * fetch blocked / errored → cannot verify; left unchanged, noted.

Word-boundary matching means the handle itself never self-corroborates: the page
for ``amandawademan`` contains that concatenated handle, but ``\bwademan\b`` only
matches a *standalone* "wademan" (e.g. a real display name), not the handle echo.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request

from harrier.distinct import COMMON_SURNAMES
from harrier.schema import Finding

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_FETCH_TIMEOUT = 10
_DEAD_STATUSES = {404, 410}
_UNVERIFIABLE_STATUSES = {0, 401, 403, 429, 503}

# Many SPAs answer 200 with a "not found" body (a soft-404). These phrases in the
# rendered/identifying text mean the profile does not exist despite the 200.
_SOFT_404_PHRASES = (
    "page not found", "couldn't find", "could not find this", "user not found",
    "page doesn't exist", "page does not exist", "no longer available",
    "sorry, we couldn't", "this page is not available", "content is not available",
)


def _fetch(url: str, timeout: int = _FETCH_TIMEOUT) -> tuple[int, str]:
    """GET a URL; return (status, text). status 0 on network error."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(200_000).decode("utf-8", "replace")
            return getattr(resp, "status", 200) or 200, body
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception:  # noqa: BLE001 — any network failure is "unverifiable"
        return 0, ""


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _identifying_text(body: str) -> str:
    """Lowercased blob of the identity-bearing page parts (title/meta/og/text)."""
    parts: list[str] = []
    for m in re.finditer(r"<title[^>]*>(.*?)</title>", body, re.I | re.S):
        parts.append(m.group(1))
    for m in re.finditer(
        r'<meta[^>]+(?:name|property)=["\'](?:description|og:[^"\']+)["\']'
        r'[^>]*content=["\']([^"\']*)["\']',
        body,
        re.I,
    ):
        parts.append(m.group(1))
    # a bounded sample of de-tagged body text
    text = _WS_RE.sub(" ", _TAG_RE.sub(" ", body))
    parts.append(text[:4000])
    return " ".join(parts).lower()


def _strong_tokens(anchor: dict) -> list[str]:
    """Distinctive anchor tokens: uncommon surnames + location words (len>=4)."""
    toks: set[str] = set()
    for key in ("last", "maiden", "married"):
        v = (anchor.get(key) or "").strip().lower()
        if len(v) >= 5 and v not in COMMON_SURNAMES:
            toks.add(v)
    for key in ("city", "state"):
        v = (anchor.get(key) or "").strip().lower()
        for w in re.split(r"\s+", v):
            if len(w) >= 4:
                toks.add(w)
    return sorted(toks)


def _word_present(token: str, text: str) -> bool:
    return re.search(rf"\b{re.escape(token)}\b", text) is not None


def verify_finding(finding: Finding, anchor: dict, timeout: int = _FETCH_TIMEOUT) -> Finding:
    """Fetch a finding's profile and update it against the anchor (in place)."""
    if not finding.url:
        return finding
    status, body = _fetch(finding.url, timeout)
    raw = dict(finding.raw)

    if status in _DEAD_STATUSES:
        finding.exists = False
        finding.confidence = "low"
        finding.reason = f"verify: HTTP {status} — profile not found (enumeration false positive)"
        raw["verify"] = {"status": status, "verdict": "false_positive"}
        finding.raw = raw
        return finding

    if status in _UNVERIFIABLE_STATUSES:
        raw["verify"] = {"status": status, "verdict": "unverifiable"}
        finding.reason = (finding.reason + " · " if finding.reason else "") + \
            f"verify: unreachable (HTTP {status}) — confirm manually"
        finding.raw = raw
        return finding

    # Reachable (2xx). First: soft-404 pages that answer 200 with a "not found" body.
    text = _identifying_text(body)
    if any(p in text for p in _SOFT_404_PHRASES):
        finding.exists = False
        finding.confidence = "low"
        finding.reason = "verify: soft-404 — page reports the profile does not exist"
        raw["verify"] = {"status": status, "verdict": "false_positive"}
        finding.raw = raw
        return finding

    matched = [t for t in _strong_tokens(anchor) if _word_present(t, text)]
    if matched:
        finding.exists = True
        finding.confidence = "high" if len(matched) >= 2 else "medium"
        finding.reason = f"verify: corroborated by {', '.join(matched)}"
        raw["verify"] = {"status": status, "verdict": "corroborated", "matched": matched}
        finding.raw = raw
        return finding

    # No corroboration. If the handle isn't even present in the readable text, the
    # 200 is a JS shell / generic page we couldn't actually read — say so honestly
    # rather than implying we inspected the profile and found nothing.
    norm = re.sub(r"[^a-z0-9]", "", text)
    sel = re.sub(r"[^a-z0-9]", "", (finding.selector or "").lower())
    if sel and sel not in norm:
        raw["verify"] = {"status": status, "verdict": "unverifiable"}
        finding.reason = (finding.reason + " · " if finding.reason else "") + \
            "verify: 200 but JS-rendered/soft page — content not readable, confirm manually"
    else:
        raw["verify"] = {"status": status, "verdict": "reachable_no_corroboration"}
        finding.reason = (finding.reason + " · " if finding.reason else "") + \
            "verify: reachable, no anchor corroboration on page"
    finding.raw = raw
    return finding


def verify_findings(
    findings: list[Finding], anchor: dict, max_verify: int = 12,
    timeout: int = _FETCH_TIMEOUT,
) -> tuple[list[Finding], dict]:
    """Verify up to ``max_verify`` findings that have a URL. Returns (findings, stats)."""
    stats = {"verified": 0, "false_positive": 0, "corroborated": 0, "unverifiable": 0}
    budget = max_verify
    for f in findings:
        if budget <= 0 or not f.url:
            continue
        budget -= 1
        verify_finding(f, anchor, timeout=timeout)
        verdict = (f.raw.get("verify") or {}).get("verdict")
        stats["verified"] += 1
        if verdict == "false_positive":
            stats["false_positive"] += 1
        elif verdict == "corroborated":
            stats["corroborated"] += 1
        elif verdict == "unverifiable":
            stats["unverifiable"] += 1
    return findings, stats
