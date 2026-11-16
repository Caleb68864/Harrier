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

import http.client
import ipaddress
import re
import socket
import ssl
from urllib.parse import urljoin, urlsplit

from harrier.distinct import COMMON_SURNAMES
from harrier.schema import Finding
from harrier.tradecraft import likelihood_for_verdict

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


def _is_http_url(url) -> bool:
    """Only http(s) URLs are ever fetched or rendered (SSRF / local-file guard)."""
    return isinstance(url, str) and url.lower().startswith(("http://", "https://"))


def _ip_is_public(addr: str) -> bool:
    """True only for globally routable unicast addresses.

    Refuses loopback, RFC1918/ULA private, link-local (incl. the 169.254.169.254
    cloud-metadata endpoint), CGNAT, multicast, reserved and unspecified.
    """
    try:
        ip = ipaddress.ip_address(addr.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def _resolve_public(host: str) -> str | None:
    """Resolve ``host`` once; return one address iff EVERY record is public.

    Every resolved address must be public: a host with any private/loopback/
    link-local A/AAAA record is refused, and so is a resolution failure. The
    returned address is the one :func:`_fetch` connects to, so the address
    that was checked is the address that is used (no DNS-rebinding window).
    """
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OSError):
        return None
    addrs = [info[4][0] for info in infos]
    if not addrs or not all(_ip_is_public(a) for a in addrs):
        return None
    return addrs[0].split("%", 1)[0]


def _is_public_http_url(url) -> bool:
    """http(s) URL whose host resolves ONLY to public addresses (SSRF guard).

    Used as a pre-check (and by the Playwright route guard). The plain fetch
    does not rely on it alone: :func:`_fetch` resolves once per hop and
    connects to that pinned address.
    """
    return _pinned_target(url) is not None


def _pinned_target(url) -> tuple[str, str, int, str] | None:
    """``(scheme, host, port, ip)`` for a fetchable URL, else None."""
    if not _is_http_url(url):
        return None
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port
    except ValueError:
        return None
    if not host:
        return None
    ip = _resolve_public(host)
    if ip is None:
        return None
    scheme = parts.scheme.lower()
    return scheme, host, port or (443 if scheme == "https" else 80), ip


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """HTTP connection to a pre-validated IP; Host header keeps the hostname."""

    def __init__(self, host, port, ip, **kw):
        super().__init__(host, port, **kw)
        self._pinned_ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._pinned_ip, self.port),
                                             self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection to a pre-validated IP; SNI and certificate checks use
    the hostname, so TLS still verifies the site we meant to reach."""

    def __init__(self, host, port, ip, **kw):
        kw.setdefault("context", ssl.create_default_context())
        super().__init__(host, port, **kw)
        self._pinned_ip = ip

    def connect(self):
        sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


_MAX_REDIRECTS = 5
_REDIRECT_CODES = {301, 302, 303, 307, 308}


def _fetch(url: str, timeout: int = _FETCH_TIMEOUT) -> tuple[int, str, str]:
    """Plain GET; return ``(status, text, final_url)``. status 0 on network error.

    SSRF guard: only http(s) is fetched, and on EVERY hop (the first request
    and each redirect) the host is resolved once, every address must be public,
    and the connection goes to that checked address. A hostile DNS server can't
    answer "public" for the check and "private" for the connect.
    """
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        target = _pinned_target(current)
        if target is None:
            return 0, "", current
        scheme, host, port, ip = target
        parts = urlsplit(current)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        cls = _PinnedHTTPSConnection if scheme == "https" else _PinnedHTTPConnection
        conn = cls(host, port, ip, timeout=timeout)
        try:
            conn.request("GET", path, headers={"User-Agent": _UA,
                                               "Accept": "*/*",
                                               "Connection": "close"})
            resp = conn.getresponse()
            status = resp.status
            if status in _REDIRECT_CODES:
                location = resp.getheader("Location")
                if not location:
                    return status, "", current
                current = urljoin(current, location.strip())
                continue
            if not 200 <= status < 300:
                return status, "", current
            body = resp.read(200_000).decode("utf-8", "replace")
            return status, body, current
        except Exception:  # noqa: BLE001 — any network failure is "unverifiable"
            return 0, "", current
        finally:
            conn.close()
    return 0, "", current  # too many redirects


def _route_guard(route) -> None:
    """Playwright route handler: abort any request to a non-public host."""
    if _is_public_http_url(route.request.url):
        route.continue_()
    else:
        route.abort()


def _render_page(url: str, timeout: int = _RENDER_TIMEOUT) -> str | None:
    """Render a page in headless Chromium (executes JS). None if unavailable/failed.

    Refuses non-http(s) URLs: Chromium would happily open ``file://`` paths.
    """
    target = _pinned_target(url)
    if target is None:
        return None
    _, host, _, ip = target
    # Pin the page's own host to the address we just checked, so Chromium's
    # resolver can't be rebound to a private address for the main document.
    # Other hosts (redirects, sub-resources) still go through _route_guard,
    # which checks but cannot pin (roadmap O1c).
    pin_ip = f"[{ip}]" if ":" in ip else ip
    launch_args = [f"--host-resolver-rules=MAP {host} {pin_ip}"]
    try:
        from playwright.sync_api import sync_playwright

        from harrier.runner import run_in_thread
    except Exception:  # noqa: BLE001 — browser lib absent
        return None

    def _do() -> str:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=launch_args)
            ctx = browser.new_context(user_agent=_UA)
            page = ctx.new_page()
            # SSRF guard per request: covers redirect hops and sub-resources,
            # which the up-front URL check alone cannot see.
            page.route("**/*", _route_guard)
            try:
                page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
                page.wait_for_timeout(1500)  # let client-side JS populate
                html = page.content()
            finally:
                browser.close()
            return html

    try:
        # Playwright's sync API refuses to run inside a running asyncio loop;
        # run_in_thread offloads it off FastMCP's loop so the render fallback
        # actually works in the live server (not just in tests/CLI).
        return run_in_thread(_do)
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


def _metadata_text(finding: Finding) -> str:
    """Text from tool-extracted metadata (e.g. Maigret `ids`) for the pre-check.

    Only structured metadata counts. ``finding.reason`` is deliberately excluded:
    it is free text that often echoes the *query* (a blocked people-search
    finding's manual step quotes the searched name), which would let a finding
    corroborate itself.
    """
    ids = (finding.raw or {}).get("ids")
    if not isinstance(ids, dict):
        return ""
    return " ".join(str(v) for v in ids.values()).lower()


def _precheck_metadata(finding: Finding, anchor: dict) -> bool:
    """Corroborate from already-extracted metadata — free, no network. True if matched."""
    text = _metadata_text(finding)
    if not text:
        return False
    matched = [t for t in _strong_tokens(anchor) if _word_present(t, text)]
    if not matched:
        return False
    raw = dict(finding.raw)
    finding.exists = True
    finding.confidence = "high" if len(matched) >= 2 else "medium"
    finding.reason = f"verify: corroborated by extracted metadata ({', '.join(matched)})"
    raw["verify"] = {"status": "metadata", "verdict": "corroborated",
                     "matched": matched, "rendered": False}
    finding.raw = raw
    return True


def _url_key(url: str) -> tuple[str, str]:
    """(host without www., lowercased path without trailing slash)."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host, parts.path.lower().rstrip("/")


def _redirect_kind(requested: str, final: str | None, selector: str | None) -> str | None:
    """How a redirect changed the page: None (same profile), "root" (sent to
    the site's homepage: the profile is gone) or "away" (sent somewhere else,
    such as a login or search page: can't tell from here).

    Scheme, ``www.``, letter case and a trailing slash don't count as a
    change, and neither does a redirect whose path still names the handle.
    """
    if not final or final == requested:
        return None
    try:
        req_host, req_path = _url_key(requested)
        fin_host, fin_path = _url_key(final)
    except ValueError:
        return "away"
    if (req_host, req_path) == (fin_host, fin_path):
        return None
    handle = re.sub(r"[^a-z0-9]", "", (selector or "").lower())
    if not handle:
        handle = re.sub(r"[^a-z0-9]", "", req_path.rsplit("/", 1)[-1])
    if handle and handle in re.sub(r"[^a-z0-9]", "", fin_path):
        return None
    return "root" if not fin_path else "away"


def verify_finding(finding: Finding, anchor: dict, timeout: int = _FETCH_TIMEOUT,
                   render_fn=None) -> Finding:
    """Fetch (and optionally render) a finding's profile; update it (in place)."""
    # Phase 3a: corroborate from tool-extracted metadata first — free, no fetch.
    if _precheck_metadata(finding, anchor):
        return finding
    if not finding.url:
        return finding
    raw = dict(finding.raw)
    if not _is_http_url(finding.url):
        # Never fetch OR render a non-http(s) URL (file://, ftp://, javascript:).
        raw["verify"] = {"status": 0, "verdict": "unverifiable", "rendered": False}
        finding.reason = (finding.reason + " · " if finding.reason else "") + \
            "verify: non-http(s) URL refused — confirm manually"
        finding.raw = raw
        return finding
    fetched = _fetch(finding.url, timeout)
    status, body = fetched[0], fetched[1]
    final_url = fetched[2] if len(fetched) > 2 else finding.url

    # A deleted profile often redirects (to the homepage, a login page, a
    # search page) and the final page answers 200. That is not a live profile.
    moved = _redirect_kind(finding.url, final_url, finding.selector) \
        if 200 <= status < 300 else None
    if moved == "root":
        finding.exists = False
        finding.confidence = "low"
        finding.reason = (f"verify: redirected to the site homepage ({final_url}) "
                          "— profile not found (enumeration false positive)")
        raw["verify"] = {"status": status, "verdict": "false_positive",
                         "rendered": False, "final_url": final_url}
        finding.raw = raw
        return finding
    if moved == "away":
        # Not proof of deletion (some sites send anonymous visitors to a
        # login page), but the page we got is not the profile. A render would
        # follow the same redirect, so don't try one.
        raw["verify"] = {"status": status, "verdict": "unverifiable",
                         "rendered": False, "final_url": final_url,
                         "redirected": True}
        finding.reason = (finding.reason + " · " if finding.reason else "") + \
            f"verify: redirected away from the profile to {final_url} — confirm manually"
        finding.raw = raw
        return finding

    if status in _DEAD_STATUSES:
        finding.exists = False
        finding.confidence = "low"
        finding.reason = f"verify: HTTP {status} — profile not found (enumeration false positive)"
        raw["verify"] = {"status": status, "verdict": "false_positive", "rendered": False}
        finding.raw = raw
        return finding

    if status in _UNVERIFIABLE_STATUSES or not 200 <= status < 300:
        # Anything other than a 2xx (5xx, 400, 408, ...) carries no readable
        # profile — never classify an error page as "reachable".
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
        # A blocked finding is a manual step, not a claim (mirrors correlate's
        # pass-through): its URL is a site root, so there is nothing to verify.
        if budget <= 0 or not f.url or f.tier == "blocked":
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
        # Express the earned verdict as an ICD-203 estimative-probability term
        # (distinct from confidence). Deterministic lookup; None when unassessed.
        f.likelihood = likelihood_for_verdict(verdict, len(v.get("matched") or []))
    return findings, stats
