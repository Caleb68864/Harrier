"""Profile verification stage (roadmap Phase 3b + 3b-render).

Enumeration only proves a handle is TAKEN. This stage fetches a surfaced
finding's profile and checks it against the target anchor, DETERMINISTICALLY
(the semantic "is this the same person?" judgment stays in the /osint skill):

  * dead / 404 / soft-404 page → the enumeration hit was a FALSE POSITIVE.
  * page text corroborates a DISTINCTIVE anchor token (maiden surname, an
    uncommon location) as a standalone word → promote confidence.
  * reachable but no corroboration → left as an unverified lead.
  * fetch blocked / JS-shell → try a **Playwright render** (a real browser that
    executes JS); only if that still can't read it is the finding left
    ``unverifiable`` ("confirm manually").

Word-boundary matching means the handle itself never self-corroborates: the page
for ``amandawademan`` contains that concatenated handle, but ``\bwademan\b`` only
matches a *standalone* "wademan" (a real display name), not the handle echo.
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
_RENDER_TIMEOUT = 20
_DEAD_STATUSES = {404, 410}
_UNVERIFIABLE_STATUSES = {0, 401, 403, 429, 503}

# Many SPAs answer 200 with a "not found" body (a soft-404).
_SOFT_404_PHRASES = (
    "page not found", "couldn't find", "could not find this", "user not found",
    "page doesn't exist", "page does not exist", "no longer available",
    "sorry, we couldn't", "this page is not available", "content is not available",
)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _fetch(url: str, timeout: int = _FETCH_TIMEOUT) -> tuple[int, str]:
    """Plain GET; return (status, text). status 0 on network error."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(200_000).decode("utf-8", "replace")
            return getattr(resp, "status", 200) or 200, body
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception:  # noqa: BLE001 — any network failure is "unverifiable"
        return 0, ""


def _render_page(url: str, timeout: int = _RENDER_TIMEOUT) -> str | None:
    """Render a page in headless Chromium (executes JS). None if unavailable/failed."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001 — browser lib absent
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=_UA)
            page = ctx.new_page()
            try:
                page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
                page.wait_for_timeout(1500)  # let client-side JS populate
                html = page.content()
            finally:
                browser.close()
            return html
    except Exception:  # noqa: BLE001
        return None


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


def _classify_reachable(finding: Finding, anchor: dict, status: int, body: str,
                        rendered: bool) -> None:
    """Classify a readable (2xx) page against the anchor; update the finding."""
    text = _identifying_text(body)
    raw = dict(finding.raw)
    suffix = " (rendered)" if rendered else ""

    if any(p in text for p in _SOFT_404_PHRASES):
        finding.exists = False
        finding.confidence = "low"
        finding.reason = "verify: soft-404 — page reports the profile does not exist" + suffix
        raw["verify"] = {"status": status, "verdict": "false_positive", "rendered": rendered}
        finding.raw = raw
        return

    matched = [t for t in _strong_tokens(anchor) if _word_present(t, text)]
    if matched:
        finding.exists = True
        finding.confidence = "high" if len(matched) >= 2 else "medium"
        finding.reason = f"verify: corroborated by {', '.join(matched)}" + suffix
        raw["verify"] = {"status": status, "verdict": "corroborated",
                         "matched": matched, "rendered": rendered}
        finding.raw = raw
        return

    # No corroboration. If NOT rendered and the handle isn't even present, the 200
    # is a JS shell we couldn't read — mark unverifiable so a render can retry.
    # If rendered (we executed JS) and still nothing, it's a genuine no-match.
    norm = re.sub(r"[^a-z0-9]", "", text)
    sel = re.sub(r"[^a-z0-9]", "", (finding.selector or "").lower())
    if not rendered and sel and sel not in norm:
        raw["verify"] = {"status": status, "verdict": "unverifiable", "rendered": False}
        finding.reason = "verify: 200 but JS-rendered/soft page — content not readable, confirm manually"
    else:
        raw["verify"] = {"status": status, "verdict": "reachable_no_corroboration",
                         "rendered": rendered}
        finding.reason = "verify: reachable, no anchor corroboration on page" + suffix
    finding.raw = raw


def verify_finding(finding: Finding, anchor: dict, timeout: int = _FETCH_TIMEOUT,
                   render_fn=None) -> Finding:
    """Fetch (and optionally render) a finding's profile; update it (in place)."""
    if not finding.url:
        return finding
    status, body = _fetch(finding.url, timeout)
    raw = dict(finding.raw)

    if status in _DEAD_STATUSES:
        finding.exists = False
        finding.confidence = "low"
        finding.reason = f"verify: HTTP {status} — profile not found (enumeration false positive)"
        raw["verify"] = {"status": status, "verdict": "false_positive", "rendered": False}
        finding.raw = raw
        return finding

    if status in _UNVERIFIABLE_STATUSES:
        raw["verify"] = {"status": status, "verdict": "unverifiable", "rendered": False}
        finding.reason = (finding.reason + " · " if finding.reason else "") + \
            f"verify: unreachable (HTTP {status}) — confirm manually"
        finding.raw = raw
    else:
        _classify_reachable(finding, anchor, status, body, rendered=False)

    # Render fallback: retry JS-shell / blocked pages in a real browser.
    if render_fn and (finding.raw.get("verify") or {}).get("verdict") == "unverifiable":
        html = render_fn(finding.url)
        if html:
            _classify_reachable(finding, anchor, 200, html, rendered=True)
    return finding


def verify_findings(findings: list[Finding], anchor: dict, max_verify: int = 12,
                    timeout: int = _FETCH_TIMEOUT, render: bool = True) -> tuple[list[Finding], dict]:
    """Verify up to ``max_verify`` findings with a URL. Returns (findings, stats)."""
    stats = {"verified": 0, "false_positive": 0, "corroborated": 0,
             "unverifiable": 0, "rendered": 0}
    render_fn = _render_page if render else None
    budget = max_verify
    for f in findings:
        if budget <= 0 or not f.url:
            continue
        budget -= 1
        verify_finding(f, anchor, timeout=timeout, render_fn=render_fn)
        v = f.raw.get("verify") or {}
        stats["verified"] += 1
        if v.get("rendered"):
            stats["rendered"] += 1
        verdict = v.get("verdict")
        if verdict in stats:
            stats[verdict] += 1
    return findings, stats
