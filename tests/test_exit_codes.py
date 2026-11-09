"""Non-zero tool exits must surface as status="error" with an actionable
reason, never masquerade as "ok, nothing found" (a silent false negative)."""

import subprocess

from harrier.adapters import domain, phone, username



def _fake_proc(rc, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout,
                                       stderr=stderr)


def test_phone_nonzero_exit_is_error_with_stderr(monkeypatch):
    monkeypatch.setattr(phone, "binary_available", lambda n: True)
    monkeypatch.setattr(phone, "run_subprocess",
                        lambda args, timeout=30: _fake_proc(1, "", "invalid number format"))
    res = phone.run("+15555550100")
    assert res.status == "error"
    assert res == []
    assert "exit 1" in res.reason and "invalid number format" in res.reason


def test_domain_nonzero_exit_is_error_with_stderr(monkeypatch):
    monkeypatch.setattr(domain, "binary_available", lambda n: True)
    monkeypatch.setattr(domain, "run_subprocess",
                        lambda args, timeout=30: _fake_proc(2, "", "unrecognized arguments: -b"))
    res = domain.run("example.com")
    assert res.status == "error"
    assert "exit 2" in res.reason and "unrecognized arguments" in res.reason


def test_domain_nonzero_exit_with_report_keeps_findings(monkeypatch):
    # theHarvester can exit non-zero when one source fails but still write a
    # report — partial results win over an error.
    import json
    import os

    def fake(args, timeout=30):
        out = args[args.index("-f") + 1]
        with open(out + ".json", "w") as fh:
            json.dump({"emails": ["a@example.com"]}, fh)
        return _fake_proc(1, "", "source X failed")

    monkeypatch.setattr(domain, "binary_available", lambda n: True)
    monkeypatch.setattr(domain, "run_subprocess", fake)
    res = domain.run("example.com")
    assert res.status == "ok"
    assert len(res) == 1


def test_sherlock_nonzero_exit_without_results_is_error(monkeypatch):
    monkeypatch.setattr(username, "binary_available", lambda n: n == "sherlock")
    monkeypatch.setattr(username, "run_subprocess",
                        lambda args, timeout=30: _fake_proc(2, "", "error: unknown site"))
    res = username.run("amandab")
    assert res.status == "error"
    assert "exit 2" in res.reason and "unknown site" in res.reason


def test_maigret_nonzero_exit_without_results_is_error(monkeypatch):
    monkeypatch.setattr(username, "binary_available", lambda n: n == "maigret")
    monkeypatch.setattr(username, "run_subprocess",
                        lambda args, timeout=30: _fake_proc(1, "", "Traceback ... ImportError"))
    res = username.run("amandab", engine="maigret")
    assert res.status == "error"
    assert "ImportError" in res.reason
