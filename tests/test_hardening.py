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


# --- email: backend failures are reported, not a silent "ok" -----------------

def test_email_all_backends_failing_is_error_with_reason(monkeypatch):
    from harrier.adapters import email

    monkeypatch.setattr(email, "_lib_importable", lambda m: True)

    def boom_holehe(addr, errors=None):
        errors.append("holehe failed (ConnectError: dns)")
        return []

    def boom_social(addr, errors=None):
        errors.append("socialscan failed (RuntimeError)")
        return []

    monkeypatch.setattr(email, "_run_holehe", boom_holehe)
    monkeypatch.setattr(email, "_run_socialscan", boom_social)
    res = email.run("a@example.com")
    assert res.status == "error"
    assert "ConnectError" in res.reason and "socialscan" in res.reason


def test_email_one_backend_failing_keeps_ok_with_reason(monkeypatch):
    from harrier.adapters import email

    monkeypatch.setattr(email, "_lib_importable", lambda m: True)
    monkeypatch.setattr(email, "_run_holehe", lambda a, errors=None: [])

    def boom_social(addr, errors=None):
        errors.append("socialscan failed (RuntimeError)")
        return []

    monkeypatch.setattr(email, "_run_socialscan", boom_social)
    res = email.run("a@example.com")
    assert res.status == "ok"
    assert "socialscan failed" in res.reason


def test_holehe_import_failure_records_reason(monkeypatch):
    import builtins

    from harrier.adapters import email

    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name.startswith("holehe"):
            raise ImportError("no holehe")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    errors: list[str] = []
    assert email._run_holehe("a@example.com", errors) == []
    assert errors and "holehe import failed" in errors[0]


# --- verify: scheme guard on the render path; non-2xx is never "reachable" ---

def test_verify_never_renders_non_http_url(monkeypatch):
    from harrier import verify
    from harrier.schema import Finding

    rendered: list[str] = []

    def render(url):
        rendered.append(url)
        return "<html><title>wademan</title></html>"

    for bad in ("file:///etc/passwd", "ftp://example.com/x", "javascript:alert(1)"):
        f = Finding(selector="amandawademan", source_tool="sherlock", url=bad,
                    exists=True)
        verify.verify_finding(f, {"maiden": "Wademan"}, render_fn=render)
        assert f.raw["verify"]["verdict"] == "unverifiable"
        assert f.confidence == "low"
    assert rendered == []

    # _render_page itself must refuse too (defense in depth).
    assert verify._render_page("file:///etc/passwd") is None


def test_verify_server_error_is_unverifiable_not_reachable(monkeypatch):
    from harrier import verify
    from harrier.schema import Finding

    for code in (500, 502, 504, 400, 408):
        monkeypatch.setattr(verify, "_fetch", lambda url, timeout=10, c=code: (c, ""))
        f = Finding(selector="amandawademan", source_tool="sherlock",
                    url="https://example.com/amandawademan", exists=True)
        verify.verify_finding(f, {"maiden": "Wademan"}, render_fn=None)
        v = f.raw["verify"]
        assert v["verdict"] == "unverifiable", code
        assert v["status"] == code
        assert "200" not in f.reason


# --- input validation ---------------------------------------------------------

def test_validate_selector_rejects_leading_dash_option_injection():
    import pytest

    from harrier.adapters import SelectorError, validate_selector

    for bad in ("--output=evil.txt", "-h", "--version", " -x"):
        with pytest.raises(SelectorError):
            validate_selector(bad)
    assert validate_selector("a-b") == "a-b"  # interior dashes are fine


def test_username_and_domain_refuse_option_like_selectors(monkeypatch):
    from harrier.adapters import domain, username

    called = []
    monkeypatch.setattr(username, "binary_available", lambda n: True)
    monkeypatch.setattr(username, "run_subprocess", lambda *a, **k: called.append(a))
    monkeypatch.setattr(domain, "binary_available", lambda n: True)
    monkeypatch.setattr(domain, "run_subprocess", lambda *a, **k: called.append(a))
    assert username.run("--output=x.txt").status == "error"
    assert domain.run("--filename=x.json").status == "error"
    assert called == []


def test_generate_candidates_respects_zero_and_negative_max():
    from harrier.candidates import generate_candidates

    assert generate_candidates("amanda", "bennett", max=0) == []
    assert generate_candidates("amanda", "bennett", max=-3) == []
    assert len(generate_candidates("amanda", "bennett", max=1)) == 1


def test_investigate_clamps_max_rounds(monkeypatch):
    from harrier import investigate as inv
    from harrier.adapters import AdapterResult
    from harrier.schema import Finding

    n = {"i": 0}

    def fake_sweep(name, **kw):
        # Every round "discovers" a brand-new distinctive surname.
        n["i"] += 1
        tok = "zzq" + "abcdefghijklmnopqrstuvwxyz"[n["i"] % 26] * 6
        f = Finding(selector="x", source_tool="maigret", url=f"https://e.com/{n['i']}",
                    exists=True, raw={"ids": {"fullname": tok},
                                      "verify": {"verdict": "corroborated"}})
        return {"findings": [f], "sources": []}

    monkeypatch.setattr(inv.sweep_mod, "person_sweep", fake_sweep)
    monkeypatch.setattr(inv.court_mod, "run",
                        lambda *a, **k: AdapterResult(status="empty", tool="courtlistener"))
    res = inv.investigate("Amanda Bennett", max_rounds=10_000)
    assert res["rounds_run"] <= inv.MAX_ROUNDS


# --- assist: no "None" in queries; jurisdiction only from a 2-letter code ------

def test_assist_no_none_in_links_without_location():
    from harrier.assist import manual_assist_links

    links = manual_assist_links("Amanda Bennett")
    assert all("None" not in (l["url"] + l["note"]) for l in links)


def test_assist_opencorporates_jurisdiction_is_valid():
    from harrier.assist import manual_assist_links

    def oc(state):
        return next(l["url"] for l in manual_assist_links("Amanda Bennett", state=state)
                    if l["site"] == "OpenCorporates")

    assert oc("NE").endswith("&jurisdiction_code=us_ne")
    assert "jurisdiction_code" not in oc("New York")  # no space / bogus code


# --- graph: tolerate malformed input findings; emit well-formed GraphML -------

def test_parse_findings_skips_invalid_with_actionable_errors():
    from harrier.graph import parse_findings

    good = {"selector": "amandab", "source_tool": "sherlock",
            "url": "https://github.com/amandab", "value": "https://github.com/amandab"}
    fs, errors = parse_findings([good, {"selector": "x"}, "junk", {**good, "confidence": "huge"}])
    assert len(fs) == 1
    assert len(errors) == 3
    assert errors[0]["index"] == 1 and "source_tool" in errors[0]["error"]
    assert errors[1]["index"] == 2


def test_graphml_strips_xml_illegal_control_chars():
    import xml.dom.minidom

    from harrier.graph import build_graph, to_graphml
    from harrier.schema import Finding

    f = Finding(selector="a", source_tool="sherlock", value="bad\x00\x0bname\x1f")
    xml_text = to_graphml(build_graph([f], {"name": "Amanda\x07 Bennett"}))
    xml.dom.minidom.parseString(xml_text)  # raises on illegal chars


# --- logging: degraded jobs are logged with tool + cause ----------------------

def test_log_degraded_jobs(caplog):
    import logging

    from harrier import sweep

    rows = [("username", "error", []), ("email", "ok", []), ("phone", "unavailable", [])]
    reasons = ["sherlock failed (exit 2)", None, "phoneinfoga binary not found"]
    with caplog.at_level(logging.WARNING, logger="harrier.sweep"):
        sweep._log_degraded(rows, reasons)
    text = caplog.text
    assert "tool=username status=error" in text and "exit 2" in text
    assert "tool=phone status=unavailable" in text
    assert "tool=email" not in text


# --- timeouts are clamped to a sane range -------------------------------------

def test_clamp_timeout():
    from harrier.adapters import MAX_TIMEOUT, clamp_timeout

    assert clamp_timeout(0) == 1
    assert clamp_timeout(-5) == 1
    assert clamp_timeout(10**9) == MAX_TIMEOUT
    assert clamp_timeout("junk") == 30
    assert clamp_timeout(None) == 30
    assert clamp_timeout(45) == 45


def test_run_subprocess_clamps_timeout(monkeypatch):
    import harrier.adapters as adapters

    seen = {}

    def fake_run(args, **kw):
        seen["timeout"] = kw["timeout"]
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(adapters.subprocess, "run", fake_run)
    adapters.run_subprocess(["true"], timeout=0)
    assert seen["timeout"] == 1
    adapters.run_subprocess(["true"], timeout=99999)
    assert seen["timeout"] == adapters.MAX_TIMEOUT


def test_court_clamps_timeout(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["timeout"] = timeout
        raise OSError("offline")

    monkeypatch.setattr(court.urllib.request, "urlopen", fake_urlopen)
    res = court.run("Amanda Bennett", timeout=-3)
    assert res.status == "unavailable"
    assert seen["timeout"] == 1
