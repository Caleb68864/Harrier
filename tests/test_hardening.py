"""Hardening regressions (2026-11-09): adapters must never raise on malformed
tool/API output and must report actionable reasons on failure."""

import io
import json
import subprocess

import harrier.adapters.court as court
import harrier.adapters.genealogy as genealogy
from harrier.adapters import domain, phone


def _urlopen_returning(payload):
    class Ctx:
        def __enter__(self):
            return io.BytesIO(json.dumps(payload).encode())

        def __exit__(self, *a):
            return False

    return lambda req, timeout=15: Ctx()


# --- malformed JSON shapes ----------------------------------------------------

def test_court_non_dict_payload_does_not_raise(monkeypatch):
    monkeypatch.setattr(court, "_fetch", lambda q, t: (200, ["not", "a", "dict"]))
    res = court.run("Amanda Bennett")
    assert res.status == "empty"
    assert res == []


def test_court_non_string_fields_do_not_raise(monkeypatch):
    payload = {"results": [{"caseName": 12345, "absolute_url": 7, "court": None}]}
    monkeypatch.setattr(court, "_fetch", lambda q, t: (200, payload))
    res = court.run("Amanda Bennett")
    assert res.status == "ok"
    assert res[0].value == "12345"
    assert res[0].url is None


def test_genealogy_malformed_payloads_do_not_raise(monkeypatch):
    monkeypatch.setenv("FAMILYSEARCH_ACCESS_TOKEN", "x")
    for payload in (["junk"], {"entries": ["junk", {"content": "x"}]},
                    {"entries": [{"content": {"gedcomx": {"persons": ["x"]}}}]},
                    {"entries": [{"content": {"gedcomx": {"persons": [
                        {"names": [{"nameForms": []}]}]}}}]}):
        monkeypatch.setattr(genealogy.urllib.request, "urlopen",
                            _urlopen_returning(payload))
        res = genealogy.run("Amanda", "Bennett")
        assert res.status in ("ok", "empty")


def test_domain_report_malformed_shapes(tmp_path):
    (tmp_path / "report.json").write_text(json.dumps(["not a dict"]))
    assert domain._parse_report(str(tmp_path), "example.com") == []
    (tmp_path / "report.json").write_text(
        json.dumps({"emails": [None, 5, "a@example.com"], "hosts": "notalist"}))
    res = domain._parse_report(str(tmp_path), "example.com")
    assert [f.value for f in res] == ["a@example.com"]


def test_phone_json_non_string_carrier_does_not_raise():
    out = json.dumps({"result": {"carrier": {"name": "X"}, "country": 1}})
    res = phone._parse(out, "+15555550100")
    assert len(res) == 1
    assert isinstance(res[0].value, str)


# --- sweep sources[] carries the cause of degradation -------------------------

def test_sweep_sources_carry_exception_reason():
    from harrier import sweep
    from harrier.adapters import AdapterResult

    raw = [("username", KeyError("site_list")),
           ("username", AdapterResult(status="error", tool="sherlock",
                                      reason="sherlock failed (exit 2)")),
           ("court", TimeoutError())]
    rows = [sweep._normalize(t, r) for t, r in raw]
    reasons = [sweep._reason(r) for _, r in raw]
    by_tool = {s["tool"]: s for s in sweep._merge_sources(rows, reasons)}
    assert "KeyError: 'site_list'" in by_tool["username"]["reasons"]
    assert "sherlock failed (exit 2)" in by_tool["username"]["reasons"]
    assert by_tool["court"]["status"] == "timeout"
    assert by_tool["court"]["reasons"]


def test_merge_sources_backward_compatible_without_reasons():
    from harrier import sweep
    out = sweep._merge_sources([("email", "ok", [])])
    assert out == [{"tool": "email", "status": "ok", "count": 0}]
