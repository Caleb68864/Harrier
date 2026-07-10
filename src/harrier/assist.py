"""Manual-assist link generator (roadmap Phase 4).

The research verdict: do NOT build anti-bot bypass. The durable Cloudflare
bypasses are paid or a losing maintenance treadmill, and actively defeating a bot
challenge strengthens a ToS-circumvention claim. Instead, hand the analyst
**pre-filled deep links** — their real browser sails past the wall Harrier can't,
and Harrier never touches the block or the site's ToS.

This module builds those links for a person across the free / un-walled sources
that actually IDENTIFY someone (genealogy, courts, obituaries, business, records)
plus the Cloudflare-walled people-search aggregators. It makes NO network call —
it only constructs URLs. Deep-linkable GET endpoints are pre-filled; form/POST
sites are given as "open + search for X" with the query spelled out.

Highest-yield for a maiden-name case (per the research): FamilySearch + obituaries
— a married name → maiden name → family network is a genealogy problem.
"""

from __future__ import annotations

from urllib.parse import quote, quote_plus


def _g(query: str) -> str:
    """A Google search deep link (always correct; the reliable backbone)."""
    return f"https://www.google.com/search?q={quote_plus(query)}"


def manual_assist_links(
    name: str,
    city: str | None = None,
    state: str | None = None,
    maiden: str | None = None,
    married: str | None = None,
) -> list[dict]:
    """Build pre-filled search links for a person. Pure function, no network.

    Returns a list of ``{category, site, url, prefilled, note}`` dicts, ordered
    by yield for identifying a private individual.
    """
    name = (name or "").strip()
    parts = name.split()
    first = parts[0] if parts else ""
    last = parts[-1] if len(parts) > 1 else ""
    loc = ", ".join(p for p in (city, state) if p)
    loc_q = f" {loc}" if loc else ""
    links: list[dict] = []

    def add(category, site, url, prefilled, note):
        links.append({"category": category, "site": site, "url": url,
                      "prefilled": prefilled, "note": note})

    # --- Genealogy / maiden-name resolution (highest yield for this case) ------
    if first:
        fam = (f"https://www.familysearch.org/search/record/results?"
               f"q.givenName={quote(first)}")
        if maiden or last:
            fam += f"&q.surname={quote(maiden or last)}"
        if married and married != (maiden or last):
            fam += f"&q.spouseSurname={quote(married)}"
        add("genealogy", "FamilySearch",
            fam, True,
            "Free (nonprofit). Best free maiden-name resolver — marriage & death "
            "records tie married→maiden→family. Sign in (free) to see full records.")
    add("obituary", "Google → obituaries",
        _g(f'"{name}" obituary OR obituaries{loc_q}'), True,
        "Highest-yield family-network + maiden-name source; funeral-home/Legacy "
        "pages are fetchable. Look for surviving-relatives lists.")
    if maiden and first:
        add("obituary", "Google → maiden-name obituary",
            _g(f'"{first} {maiden}" obituary OR wedding OR engagement{loc_q}'), True,
            "Search the MAIDEN name — wedding/engagement/obit notices bridge the "
            "married and maiden identities.")

    # --- People-search aggregators (Cloudflare-walled to bots; your browser is fine)
    ppl = quote(name)
    loc_p = quote(loc) if loc else ""
    add("people-search", "TruePeopleSearch",
        f"https://www.truepeoplesearch.com/results?name={ppl}"
        + (f"&citystatezip={loc_p}" if loc_p else ""),
        True,
        "Cloudflare-blocked to automation (see docs/ss04-spike-evidence.md). Open "
        "in YOUR browser — address history, relatives, phone, AKA surnames.")
    if first and last:
        slug = f"{first}-{last}".lower()
        locslug = f"_{city.replace(' ', '-')}-{state}".lower() if (city and state) else ""
        add("people-search", "FastPeopleSearch",
            f"https://www.fastpeoplesearch.com/name/{quote(slug)}{quote(locslug)}",
            True, "Same data class as TruePeopleSearch; also Cloudflare-walled to bots.")

    # --- Courts / legal (name-change & divorce = maiden-name leads) ------------
    add("court", "CourtListener / RECAP",
        f"https://www.courtlistener.com/?q={quote_plus(chr(34) + name + chr(34))}",
        True, "Free API/site, millions of federal dockets. Divorce/name-change → "
        "maiden-name leads. State cases: use the state judiciary portal below.")
    if state:
        add("court", "State court records",
            _g(f"{state} judicial case search {name}"), True,
            "State trial-court records are form-gated; this finds the right portal "
            "to search by hand.")

    # --- Sex-offender registry (form-gated; open + search) --------------------
    add("records", "NSOPW (sex-offender registry)",
        "https://www.nsopw.gov/", False,
        f"Form-gated national registry. Open and search Last='{last or name}'"
        + (f", state {state}." if state else "."))

    # --- Business / entity ----------------------------------------------------
    oc = f"https://opencorporates.com/companies?q={quote_plus(name)}"
    if state:
        oc += "&jurisdiction_code=us_" + state.lower()
    add("business", "OpenCorporates", oc, True,
        "Person → registered entity → address / registered agent.")
    if state:
        add("business", "State Sec. of State business search",
            _g(f"{state} secretary of state business entity search"), True,
            "Free official entity/trade-name search (form-gated); this finds it.")

    # --- Public records: property, unclaimed property -------------------------
    add("records", "County assessor / GIS property",
        _g(f"{loc or state} county assessor property search"), True,
        "Free, openly queryable; places the subject at an address.")
    add("records", "Unclaimed property (MissingMoney)",
        "https://www.missingmoney.com/en/", False,
        f"Free/government-backed. Open and search '{name}' — corroborates "
        "name→city/state + a holder institution.")

    return links


def register(app) -> None:
    """Register the `manual_assist` MCP tool."""

    @app.tool(name="manual_assist")
    def manual_assist(
        name: str,
        city: str | None = None,
        state: str | None = None,
        maiden: str | None = None,
        married: str | None = None,
    ) -> dict:
        """Pre-filled search links for walled/gated free sources (makes no network call)."""
        links = manual_assist_links(name, city=city, state=state,
                                    maiden=maiden, married=married)
        return {"count": len(links), "links": links}
