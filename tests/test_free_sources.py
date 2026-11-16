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


# theHarvester 4.11.1's ``Core.get_supportedengines()``, copied verbatim.
# theHarvester refuses the whole ``-b`` list if one name is not in here.
_HARVESTER_4_11_1_ENGINES = frozenset({
    "baidu", "bevigil", "bitbucket", "bufferoverun", "builtwith", "brave",
    "censys", "certspotter", "chaos", "commoncrawl", "criminalip", "crtsh",
    "dehashed", "dnsdumpster", "duckduckgo", "dymo", "fofa", "fullhunt",
    "github-code", "gitlab", "hackertarget", "haveibeenpwned", "hudsonrock",
    "hunter", "hunterhow", "intelx", "leakix", "leaklookup", "linkedin",
    "linkedin_links", "mojeek", "netcraft", "netlas", "omnisint", "onyphe",
    "otx", "pentesttools", "projectdiscovery", "rapiddns", "robtex",
    "rocketreach", "securityscorecard", "securityTrails", "sherlockeye",
    "shodan", "shodanInternetDB", "subdomaincenter", "subdomainfinderc99",
    "sublist3r", "thc", "threatcrowd", "tomba", "urlscan", "venacus",
    "virustotal", "waybackarchive", "whoisxml", "windvane", "yahoo",
    "zoomeye", "zoomeyeapi",
})
# Modules in 4.11.1 that need an API key (api-keys.yaml / README), except
# hackertarget, whose key is optional.
_HARVESTER_4_11_1_KEYED = frozenset({
    "bevigil", "bitbucket", "brave", "bufferoverun", "builtwith", "censys",
    "criminalip", "dehashed", "dnsdumpster", "dymo", "fofa", "fullhunt",
    "github-code", "haveibeenpwned", "hunter", "hunterhow", "intelx",
    "leakix", "leaklookup", "mojeek", "netlas", "onyphe", "pentesttools",
    "projectdiscovery", "rocketreach", "securityscorecard", "securityTrails",
    "sherlockeye", "shodan", "tomba", "venacus", "virustotal", "whoisxml",
    "windvane", "zoomeye",
})


def test_free_sources_pinned_to_checked_harvester_version():
    # Changing the list (or the version) means re-checking it against a real
    # theHarvester: see the comment above FREE_SOURCES.
    assert domain.HARVESTER_VERSION_CHECKED == "4.11.1"
    assert domain.FREE_SOURCES == (
        "certspotter", "commoncrawl", "crtsh", "hackertarget", "otx",
        "rapiddns", "robtex", "subdomaincenter", "thc", "urlscan",
        "waybackarchive",
    )
    assert set(domain.FREE_SOURCES) <= _HARVESTER_4_11_1_ENGINES
    assert not set(domain.FREE_SOURCES) & _HARVESTER_4_11_1_KEYED
    # Removed upstream; an unknown name makes theHarvester reject the run.
    assert "anubis" not in domain.FREE_SOURCES
    assert "threatminer" not in domain.FREE_SOURCES
    # Keyless but resolves the target itself before querying (not purely
    # passive); see the comment above FREE_SOURCES.
    assert "shodanInternetDB" not in domain.FREE_SOURCES
    # _validate_sources lowercases input, so every entry must be lowercase.
    assert all(s == s.lower() for s in domain.FREE_SOURCES)


def test_threatcrowd_is_excluded_and_the_harvest_budget_covers_the_slow_sources():
    # threatcrowd is plain http in 4.11.1; the owner excluded it. One run hits
    # every source and a timeout returns nothing, so the budget is 120 s.
    assert "threatcrowd" not in domain.FREE_SOURCES
    assert domain.HARVEST_TIMEOUT == 120
    import inspect
    assert inspect.signature(domain.run).parameters["timeout"].default == 120
