"""Tests for the free tool adapters (SS-03).

These mock the external tools — they never require Sherlock/Maigret/holehe/etc.
to actually run. The contract under test: a missing tool → status="unavailable",
empty findings, no exception; bad selectors are rejected; parsers normalize to
Finding.
"""

import os

import pytest

from harrier.adapters import (
    AdapterResult,
    SelectorError,
    validate_selector,
)
from harrier.adapters import domain, email, phone, username
from harrier.schema import Finding


# --- shared helper contract ---------------------------------------------------

def test_validate_selector_rejects_metachars():
    for bad in ["a;rm -rf", "a|b", "a&b", "a$(x)", "a`b`", "a b", "", ">out"]:
        with pytest.raises(SelectorError):
            validate_selector(bad)


def test_validate_selector_accepts_clean():
    assert validate_selector("amanda.bennett") == "amanda.bennett"
    assert validate_selector("  awademan ") == "awademan"


def test_adapter_result_is_list_with_status():
    r = AdapterResult([], status="unavailable", tool="username", reason="x")
    assert r == []
    assert r.status == "unavailable"
    assert r.tool == "username"
    assert r.findings == []


# --- username adapter ---------------------------------------------------------

def test_username_unavailable_when_binary_absent(monkeypatch):
    """Both Sherlock and Maigret missing → unavailable, [], no raise."""
    monkeypatch.setattr(username, "binary_available", lambda name: False)
    res = username.run("amandab")
    assert res.status == "unavailable"
    assert res == []


def test_username_rejects_bad_selector():
    res = username.run("amanda;rm -rf /")
    assert res.status == "error"
    assert res == []


def test_username_parses_sherlock_file(tmp_path):
    """The Sherlock result-file parser normalizes URLs to Findings."""
    f = tmp_path / "amandab.txt"
    f.write_text(
        "https://github.com/amandab\nhttps://twitter.com/amandab\nnot-a-url\n",
        encoding="utf-8",
    )
    findings = username._parse_sherlock_file(str(f), "amandab")
    assert len(findings) == 2
    assert all(isinstance(x, Finding) for x in findings)
    assert findings[0].source_tool == "sherlock"
    assert findings[0].exists is True
    assert findings[0].confidence == "low"


def test_username_sherlock_invoked_with_list_args(monkeypatch, tmp_path):
    """run_subprocess is called with a LIST (never a shell string)."""
    captured = {}

    def fake_run_subprocess(args, timeout=30):
        captured["args"] = args
        # simulate Sherlock writing its result file
        import subprocess

        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(username, "binary_available",
                        lambda name: name == "sherlock")
    monkeypatch.setattr(username, "run_subprocess", fake_run_subprocess)
    res = username.run("amandab")
    assert isinstance(captured["args"], list)
    assert "amandab" in captured["args"]
    assert res.status == "ok"


def test_maigret_parses_ids_metadata(tmp_path):
    """Phase 3a: Maigret's extracted `ids` metadata is captured on the Finding."""
    import json

    report = tmp_path / "report_awademan_simple.json"
    report.write_text(
        json.dumps({
            "SomeSite": {
                "status": {"status": "Claimed"},
                "url_user": "https://s/awademan",
                "ids": {"fullname": "Amanda Wademan", "location": "Nebraska"},
            }
        }),
        encoding="utf-8",
    )
    findings = username._parse_maigret_json(str(report), "awademan")
    assert len(findings) == 1
    assert findings[0].raw["ids"]["fullname"] == "Amanda Wademan"
    assert "Amanda Wademan" in (findings[0].reason or "")


# --- email adapter ------------------------------------------------------------

def test_email_unavailable_when_libs_absent(monkeypatch):
    monkeypatch.setattr(email, "_lib_importable", lambda module: False)
    res = email.run("amanda@example.com")
    assert res.status == "unavailable"
    assert res == []


def test_email_rejects_non_email():
    res = email.run("not-an-email")
    assert res.status == "error"
    assert res == []


# --- phone adapter (PhoneInfoga / Go — expected unavailable on this host) ------

def test_phone_unavailable_when_binary_absent(monkeypatch):
    monkeypatch.setattr(phone, "binary_available", lambda name: False)
    res = phone.run("+14025551234")
    assert res.status == "unavailable"
    assert res == []


def test_phone_rejects_bad_number():
    res = phone.run("abc")
    assert res.status == "error"


# --- domain adapter -----------------------------------------------------------

def test_domain_unavailable_when_binary_absent(monkeypatch):
    monkeypatch.setattr(domain, "binary_available", lambda name: False)
    res = domain.run("example.com")
    assert res.status == "unavailable"
    assert res == []


def test_domain_rejects_bad_domain():
    res = domain.run("notadomain")
    assert res.status == "error"


def test_domain_parses_report(tmp_path):
    import json

    report = tmp_path / "report.json"
    report.write_text(
        json.dumps({"emails": ["a@example.com"], "hosts": ["mail.example.com"]}),
        encoding="utf-8",
    )
    findings = domain._parse_report(str(tmp_path), "example.com")
    assert len(findings) == 2
    assert {f.raw["type"] for f in findings} == {"email", "host"}
