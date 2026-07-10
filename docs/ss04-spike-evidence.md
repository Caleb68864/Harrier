# SS-04 — People-Search Playwright Spike Evidence (ASM-1 gate)

**Date:** 2026-07-10
**Question (ASM-1):** Is ≥1 free people-search site reachable via headless
Playwright well enough to scrape address/relatives/phone?

**Verdict: BLOCKED.** Both candidate free sites return **HTTP 403 behind a
Cloudflare challenge**. Headless Playwright (Chromium) got **no further than a
plain HTTP request** — it hit the same Cloudflare interstitial. No stealth
escalation was attempted beyond a real desktop User-Agent; getting past an
active Cloudflare JS challenge would require anti-bot evasion that is out of
scope (and ToS-hostile) for this build.

## Method

Throwaway spike (`scratchpad/spike.py`, not committed): for each target, a plain
`urllib` GET with a desktop UA, then a headless Chromium `page.goto()` capturing
the HTTP status, page title, and block signals in the returned HTML.

## Results (real, unedited)

| Site | Plain GET | Playwright (headless Chromium) | Block signals |
|---|---|---|---|
| truepeoplesearch.com | **403** | **403**, title `truepeoplesearch.com` | `captcha`, `cloudflare` |
| fastpeoplesearch.com | **403** | **403**, title `Just a moment...` | `just a moment` (Cloudflare challenge) |

- `truepeoplesearch`: 403 with a Cloudflare CAPTCHA page (~2.1 KB challenge body).
- `fastpeoplesearch`: 403 with the classic Cloudflare `Just a moment...`
  interstitial (~6 KB JS-challenge body).

Playwright did **not** improve on the plain request — same 403, same challenge.
A plain `curl` had already returned 403 (noted in the task); this spike
confirms the browser path does not bypass it either.

## Consequence for the build (honest, no fabrication)

- The `people_search` adapter is built but **degrades to `tier="blocked"`** on
  403 / CAPTCHA / Cloudflare challenge, emitting a `Finding` whose `reason` is
  the **manual step** (open the site in a real browser and read the record by
  hand). It never fabricates a scraped result.
- The value proposition of the people-search dimension does **not** hold for
  free automated scraping of these two sites as of this date. Username/email/
  domain dimensions are unaffected and remain the sweep's real yield.
- This is the expected ASM-1 outcome, not a bug. Re-run this spike if a site's
  anti-bot posture changes or a different free source is identified.
