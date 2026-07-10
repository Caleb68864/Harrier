"""People-search adapter — consent-gated headless-browser scrape (SS-04).

The SS-04 spike (``docs/ss04-spike-evidence.md``) found both candidate free
sites (truepeoplesearch / fastpeoplesearch) sit behind a Cloudflare 403
challenge that headless Playwright does not bypass. So this adapter is built to
**degrade honestly**:

  * ``consent=False`` (default) → ``status="blocked"``, a ``blocked`` Finding
    explaining consent is required, and **no network call at all**.
  * ``consent=True`` → attempt the scrape; on 403 / CAPTCHA / Cloudflare
    challenge (the expected case today) → a ``blocked`` Finding whose ``reason``
    is the manual step (open in a real browser). It never raises, never
    fabricates a scraped record.

Rate-limited with jitter to avoid hammering the host IP. Playwright is imported
lazily so a missing browser degrades to ``unavailable`` rather than crashing.
"""

from __future__ import annotations

import random
import time
from typing import Optional

from harrier.schema import Finding

TOOL = "people_search"

# Default free target chosen by the spike. Both known free sites are Cloudflare-
# gated; this is the one whose challenge we detect and surface a manual step for.
DEFAULT_SITE = "truepeoplesearch.com"

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# HTML markers that mean "the anti-bot wall stopped us".
_BLOCK_MARKERS = ("captcha", "cloudflare", "just a moment", "access denied",
                  "unusual traffic", "verify you are", "attention required",
                  "cf-chl")

# Minimum seconds between real requests, plus jitter, to stay polite.
_MIN_INTERVAL = 3.0
_JITTER = 2.0


def _manual_step(name: str, site: str) -> str:
    return (
        f"Blocked by {site} (anti-bot / Cloudflare 403). Manual step: open "
        f"https://www.{site}/ in a real browser, search '{name}', and read the "
        f"record by hand. Automated free scraping is not available for this "
        f"site (see docs/ss04-spike-evidence.md)."
    )


def _blocked_finding(name: str, site: str, reason: Optional[str] = None) -> Finding:
    return Finding(
        selector=name,
        source_tool=TOOL,
        url=f"https://www.{site}/",
        value=None,
        exists=None,
        confidence="low",
        tier="blocked",
        reason=reason or _manual_step(name, site),
        raw={"site": site},
    )


def _looks_blocked(status: Optional[int], html: str) -> bool:
    if status is not None and status >= 400:
        return True
    low = (html or "").lower()
    return any(m in low for m in _BLOCK_MARKERS)


def run(
    name: str,
    city_or_state: Optional[str] = None,
    age: Optional[int] = None,
    consent: bool = False,
    site: str = DEFAULT_SITE,
    _sleep: bool = True,
) -> dict:
    """Look up a person on a free people-search site (consent-gated).

    Returns ``{"findings": [Finding...], "status": str}``. Never raises.

    With ``consent=False`` no network call is made and the result is
    ``blocked``. With ``consent=True`` the scrape is attempted; the expected
    outcome today is a ``blocked`` Finding carrying a manual step.
    """
    name = (name or "").strip()
    if not name:
        return {"findings": [], "status": "error"}

    if not consent:
        # Consent gate: refuse, emit a blocked Finding, make NO network call.
        return {
            "findings": [
                _blocked_finding(
                    name,
                    site,
                    reason="consent=False: scrape tier refused. Pass "
                    "consent=True to attempt the (ToS-sensitive) lookup.",
                )
            ],
            "status": "blocked",
        }

    # consent=True → attempt the real fetch.
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001 — browser lib absent
        return {
            "findings": [
                _blocked_finding(
                    name, site,
                    reason="playwright/chromium unavailable; install to attempt "
                    "the scrape, or perform the lookup manually.",
                )
            ],
            "status": "unavailable",
        }

    # Politeness: rate-limit + jitter before any real request.
    if _sleep:
        time.sleep(_MIN_INTERVAL + random.random() * _JITTER)

    status_code, html = _fetch(sync_playwright, name, city_or_state, site)

    if status_code == "ERROR":
        return {
            "findings": [
                _blocked_finding(
                    name, site,
                    reason="browser error during fetch; perform the lookup "
                    "manually (see docs/ss04-spike-evidence.md).",
                )
            ],
            "status": "unavailable",
        }

    if _looks_blocked(status_code if isinstance(status_code, int) else None, html):
        # Expected path per the spike: 403 / Cloudflare challenge.
        return {"findings": [_blocked_finding(name, site)], "status": "blocked"}

    # Unblocked path (not observed in the spike): parse records.
    findings = _parse(html, name, site)
    return {"findings": findings, "status": "ok" if findings else "empty"}


def _fetch(sync_playwright, name, city_or_state, site):
    """Perform the headless fetch. Returns (status_code|'ERROR', html)."""
    query = name.replace(" ", "%20")
    loc = f"&citystatezip={city_or_state.replace(' ', '%20')}" if city_or_state else ""
    url = f"https://www.{site}/results?name={query}{loc}"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=_UA)
            page = ctx.new_page()
            try:
                resp = page.goto(url, timeout=30000, wait_until="domcontentloaded")
                status = resp.status if resp else None
                html = page.content()
            finally:
                browser.close()
            return status, html
    except Exception:  # noqa: BLE001
        return "ERROR", ""


def _parse(html: str, name: str, site: str) -> list[Finding]:
    """Parse a successful results page. Placeholder — site is Cloudflare-gated,
    so this path is not exercised today; kept minimal and honest."""
    # If we ever get an unblocked page, emit a single scrape-tier Finding
    # pointing at it; structured extraction is deferred until a site is
    # actually reachable.
    return [
        Finding(
            selector=name,
            source_tool=TOOL,
            url=f"https://www.{site}/",
            value="results page reachable",
            exists=None,
            confidence="low",
            tier="scrape",
            raw={"site": site, "html_len": len(html or "")},
        )
    ]


def register(app) -> None:
    """Register the `people_search` MCP tool."""

    @app.tool(name="people_search")
    def people_search(
        name: str,
        city_or_state: str | None = None,
        age: int | None = None,
        consent: bool = False,
    ) -> dict:
        """Look up a person on a free people-search site (consent-gated scrape)."""
        res = run(name, city_or_state=city_or_state, age=age, consent=consent)
        return {
            "status": res["status"],
            "count": len(res["findings"]),
            "findings": [f.model_dump() for f in res["findings"]],
        }
