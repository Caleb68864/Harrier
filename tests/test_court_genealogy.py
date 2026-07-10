"""Tests for the Phase 4b structured adapters (court, genealogy). Network mocked."""

import io
import json

import harrier.adapters.court as court
import harrier.adapters.genealogy as genealogy


def test_court_parses_results(monkeypatch):
    payload = {"results": [
        {"caseName": "In re Amanda Bennett", "court": "neb",
         "dateFiled": "2019-05-01", "absolute_url": "/docket/123/",
         "docketNumber": "8:19-cv-1"},
    ]}
    monkeypatch.setattr(court, "_fetch", lambda q, t: (200, payload))
    res = court.run("Amanda Bennett", state="NE")
    assert res.status == "ok"
    assert len(res) == 1
    assert res[0].source_tool == "courtlistener"
    assert res[0].url.endswith("/docket/123/")
    assert res[0].value == "In re Amanda Bennett"


def test_court_unavailable_on_network_error(monkeypatch):
    monkeypatch.setattr(court, "_fetch", lambda q, t: (0, None))
    res = court.run("Amanda Bennett")
    assert res.status == "unavailable"
    assert res == []


def test_court_empty_name():
    assert court.run("").status == "error"


def test_genealogy_unavailable_without_token(monkeypatch):
    monkeypatch.delenv("FAMILYSEARCH_ACCESS_TOKEN", raising=False)
    res = genealogy.run("Amanda", "Bennett", maiden="Wademan")
    assert res.status == "unavailable"
    assert "FAMILYSEARCH_ACCESS_TOKEN" in (res.reason or "")
    assert res == []


def test_genealogy_parses_with_token(monkeypatch):
    monkeypatch.setenv("FAMILYSEARCH_ACCESS_TOKEN", "x")
    payload = {"entries": [
        {"id": "abc", "content": {"gedcomx": {"persons": [
            {"names": [{"nameForms": [{"fullText": "Amanda Wademan"}]}]}]}}},
    ]}

    class Ctx:
        def __enter__(self):
            return io.BytesIO(json.dumps(payload).encode())

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(genealogy.urllib.request, "urlopen",
                        lambda req, timeout=15: Ctx())
    res = genealogy.run("Amanda", "Bennett", maiden="Wademan")
    assert res.status == "ok"
    assert res[0].value == "Amanda Wademan"
    assert res[0].source_tool == "familysearch"
