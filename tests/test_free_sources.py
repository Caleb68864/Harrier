"""theHarvester is pinned to free, keyless sources (legal constraint: free public
sources only). ``-b all`` would pull in API-key / paid-tier modules."""

import subprocess

from harrier.adapters import domain


def test_domain_uses_free_source_allowlist_not_all(monkeypatch):
    seen = {}

    def fake(args, timeout=30):
        seen["b"] = args[args.index("-b") + 1]
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(domain, "binary_available", lambda n: True)
    monkeypatch.setattr(domain, "run_subprocess", fake)
    domain.run("example.com")
    used = seen["b"].split(",")
    assert "all" not in used
    assert set(used) == set(domain.FREE_SOURCES)
    for paid in ("shodan", "hunter", "censys", "securitytrails"):
        assert paid not in used


def test_domain_refuses_non_free_sources(monkeypatch):
    called = []
    monkeypatch.setattr(domain, "binary_available", lambda n: True)
    monkeypatch.setattr(domain, "run_subprocess", lambda *a, **k: called.append(a))
    for bad in ("all", "shodan", "crtsh,hunter", ""):
        res = domain.run("example.com", sources=bad)
        assert res.status == "error", bad
        assert "free keyless" in res.reason
    assert called == []
    assert domain._validate_sources("crtsh, OTX") == "crtsh,otx"
