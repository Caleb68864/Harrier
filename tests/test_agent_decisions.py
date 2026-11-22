"""Items the agent decided on 2026-11-21 under the owner's standing order
(roadmap O22-O26, O30-O32; the owner may revisit each)."""

import pytest

from harrier.adapters import court


# --- O23: no CourtListener token -> skip, with a reason, and no request -------

def test_court_without_token_makes_no_request(monkeypatch):
    monkeypatch.delenv("COURTLISTENER_TOKEN", raising=False)
    monkeypatch.delenv("HARRIER_COURT_ANONYMOUS", raising=False)

    def boom(*a, **k):
        raise AssertionError("no request without a token")

    monkeypatch.setattr(court, "_fetch", boom)
    res = court.run("Amanda Bennett")
    assert res.status == "unavailable" and res == []
    assert "COURTLISTENER_TOKEN" in res.reason
    assert "skipped" in res.reason and "manual_assist" in res.reason


def test_court_anonymous_setting_still_tries(monkeypatch):
    # HARRIER_COURT_ANONYMOUS=1 restores the old behaviour (in case
    # CourtListener reopens anonymous access).
    monkeypatch.delenv("COURTLISTENER_TOKEN", raising=False)
    monkeypatch.setenv("HARRIER_COURT_ANONYMOUS", "1")
    calls = []
    monkeypatch.setattr(court, "_fetch", lambda q, t: calls.append(q) or (200, {"results": []}))
    assert court.run("Amanda Bennett").status == "empty"
    assert calls == ['"Amanda Bennett"']


def test_court_with_token_queries(monkeypatch):
    monkeypatch.setenv("COURTLISTENER_TOKEN", "x")
    monkeypatch.delenv("HARRIER_COURT_ANONYMOUS", raising=False)
    calls = []
    monkeypatch.setattr(court, "_fetch", lambda q, t: calls.append(q) or (200, {"results": []}))
    court.run("Amanda Bennett")
    assert calls


# --- O24: Cloudflare-served is not Cloudflare-challenged ----------------------

from harrier.adapters import people_search  # noqa: E402

_CF_SERVED_RESULTS = (
    "<html><head><title>Jane Doe - Search Results</title>"
    "<script src='https://cdnjs.cloudflare.com/ajax/libs/jquery/3.7.1/jquery.min.js'></script>"
    "</head><body><div class='card'>Jane Doe, age 41, Omaha NE</div>"
    "<form><div class='g-recaptcha' data-sitekey='x'></div>Report a captcha problem</form>"
    "<script defer src='https://static.cloudflareinsights.com/beacon.min.js'></script>"
    "<footer>Protected by Cloudflare. Access denied? Contact us.</footer></body></html>"
)

# Shapes of real Cloudflare interstitials (managed challenge and block page).
_CF_CHALLENGE = (
    "<!DOCTYPE html><html lang='en-US'><head><title>Just a moment...</title></head>"
    "<body><div id='challenge-error-text'>Enable JavaScript and cookies to continue</div>"
    "<script>(function(){window._cf_chl_opt={cvId: '3'};var a=document.createElement('script');"
    "a.src='/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1?ray=x';})();</script>"
    "</body></html>"
)
_CF_BLOCK = (
    "<html><head><title>Attention Required! | Cloudflare</title></head><body>"
    "<div id='cf-error-details'><h1>Sorry, you have been blocked</h1></div></body></html>"
)


@pytest.mark.parametrize("html,blocked", [
    (_CF_SERVED_RESULTS, False),
    (_CF_CHALLENGE, True),
    (_CF_BLOCK, True),
    ("<title>Are you a robot?</title><p>captcha</p>", True),
    ("<title>Security check</title>We detected unusual traffic", True),
])
def test_block_detection_uses_challenge_markers(html, blocked):
    assert people_search._looks_blocked(200, html) is blocked


def test_403_is_still_blocked():
    assert people_search._looks_blocked(403, _CF_SERVED_RESULTS) is True
