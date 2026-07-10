"""Tests for the manual-assist link generator (Phase 4). Pure function, no network."""

from urllib.parse import unquote

from harrier.assist import manual_assist_links


def test_links_generated_and_shaped():
    links = manual_assist_links("Amanda Bennett", city="Harvard", state="NE",
                                maiden="Wademan", married="Warm")
    assert links
    for link in links:
        assert set(link) == {"category", "site", "url", "prefilled", "note"}
        assert link["url"].startswith("http")


def test_maiden_name_drives_familysearch():
    links = manual_assist_links("Amanda Bennett", maiden="Wademan")
    fs = [x for x in links if "FamilySearch" in x["site"]]
    assert fs
    assert "Wademan" in unquote(fs[0]["url"])


def test_people_search_prefilled_with_name():
    links = manual_assist_links("Amanda Bennett", city="Harvard", state="NE")
    tps = [x for x in links if "TruePeopleSearch" in x["site"]]
    assert tps and tps[0]["prefilled"] is True
    assert "Amanda Bennett" in unquote(tps[0]["url"])


def test_identity_categories_present():
    links = manual_assist_links("Amanda Bennett", state="NE", maiden="Wademan")
    cats = {x["category"] for x in links}
    assert {"genealogy", "obituary", "people-search", "court", "records"} <= cats


def test_pure_function_returns_dicts():
    links = manual_assist_links("Jane Doe")
    assert isinstance(links, list) and all(isinstance(x, dict) for x in links)
