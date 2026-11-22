"""O17: the PhoneInfoga parser against output from a real v2.11.0 binary.

Captured 2026-11-21 from the GitHub release ``phoneinfoga_Linux_x86_64.tar.gz``
(sha256 6173dfc4...2a52, ``phoneinfoga version`` -> ``PhoneInfoga
2.11.0-5f6156f``), stdout piped (so no ANSI colour). The number is a fictional
555 number. Each googlesearch category's URL list is cut to two entries; the
lines are otherwise byte-for-byte what the binary printed.
"""

from types import SimpleNamespace

from harrier.adapters import phone

# `phoneinfoga scan -n +12025550100`
_REAL_SCAN = (
    "Running scan for phone number +12025550100...\n"
    "\n"
    "Results for googlesearch\n"
    "Social media:\n"
    "\tURL: https://www.google.com/search?q=site%3Afacebook.com+intext%3A%2212025550100%22+%7C+intext%3A%22%2B12025550100%22+%7C+intext%3A%222025550100%22\n"
    "\n"
    "\tURL: https://www.google.com/search?q=site%3Atwitter.com+intext%3A%2212025550100%22+%7C+intext%3A%22%2B12025550100%22+%7C+intext%3A%222025550100%22\n"
    "Disposable providers:\n"
    "\tURL: https://www.google.com/search?q=site%3Ahs3x.com+intext%3A%2212025550100%22\n"
    "\n"
    "\tURL: https://www.google.com/search?q=site%3Areceive-sms-now.com+intext%3A%2212025550100%22+%7C+intext%3A%222025550100%22\n"
    "Reputation:\n"
    "\tURL: https://www.google.com/search?q=site%3Awhosenumber.info+intext%3A%22%2B12025550100%22+intitle%3A%22who+called%22\n"
    "\n"
    "\tURL: https://www.google.com/search?q=intitle%3A%22Phone+Fraud%22+intext%3A%2212025550100%22+%7C+intext%3A%22%2B12025550100%22+%7C+intext%3A%222025550100%22\n"
    "Individuals:\n"
    "\tURL: https://www.google.com/search?q=site%3Anuminfo.net+intext%3A%2212025550100%22+%7C+intext%3A%22%2B12025550100%22+%7C+intext%3A%222025550100%22\n"
    "\n"
    "\tURL: https://www.google.com/search?q=site%3Async.me+intext%3A%2212025550100%22+%7C+intext%3A%22%2B12025550100%22+%7C+intext%3A%222025550100%22\n"
    "General:\n"
    "\tURL: https://www.google.com/search?q=intext%3A%2212025550100%22+%7C+intext%3A%22%2B12025550100%22+%7C+intext%3A%222025550100%22+%7C+intext%3A%222025550100%22\n"
    "\n"
    "\n"
    "Results for local\n"
    "Raw local: 2025550100\n"
    "Local: (202) 555-0100\n"
    "E164: +12025550100\n"
    "International: 12025550100\n"
    "Country: US\n"
    "\n"
    "2 scanner(s) succeeded\n"
)

# `NUMVERIFY_API_KEY=bogus phoneinfoga scan -n +12025550100 -D googlesearch`
_REAL_SCAN_WITH_ERROR = (
    "Running scan for phone number +12025550100...\n"
    "\n"
    "Results for local\n"
    "Raw local: 2025550100\n"
    "Local: (202) 555-0100\n"
    "E164: +12025550100\n"
    "International: 12025550100\n"
    "Country: US\n"
    "\n"
    "The following scanners returned errors:\n"
    "numverify: Invalid authentication credentials\n"
    "\n"
    "1 scanner(s) succeeded\n"
)


def _run(monkeypatch, stdout):
    monkeypatch.setattr(phone, "binary_available", lambda n: True)
    monkeypatch.setattr(
        phone, "run_subprocess",
        lambda args, timeout=30: SimpleNamespace(returncode=0, stdout=stdout, stderr=""))
    return phone.run("+1 202 555 0100")


def test_version_checked_is_pinned():
    # Re-run a real scan before changing this: see the module docstring.
    assert phone.PHONEINFOGA_VERSION_CHECKED == "2.11.0"


def test_real_scan_keeps_googlesearch_categories(monkeypatch):
    res = _run(monkeypatch, _REAL_SCAN)
    assert res.status == "ok" and res.reason is None
    by_scanner = {f.raw["scanner"]: f for f in res}
    assert set(by_scanner) == {"googlesearch", "local"}
    assert by_scanner["local"].value == "US"
    assert by_scanner["local"].raw["fields"]["E164"] == "+12025550100"
    fields = by_scanner["googlesearch"].raw["fields"]
    # Each URL stays under the category PhoneInfoga printed it in; one flat
    # "URL" list of 45 dorks would hide which search is which.
    assert set(fields) == {"Social media", "Disposable providers", "Reputation",
                           "Individuals", "General"}
    assert len(fields["Social media"]["URL"]) == 2
    assert "facebook.com" in fields["Social media"]["URL"][0]
    assert "hs3x.com" in fields["Disposable providers"]["URL"][0]
    # A category with one entry is still a list, like the others.
    assert len(fields["General"]["URL"]) == 1
    assert isinstance(fields["General"]["URL"], list)


def test_real_scan_scanner_error_is_reported(monkeypatch):
    res = _run(monkeypatch, _REAL_SCAN_WITH_ERROR)
    assert res.status == "ok"
    assert [f.raw["scanner"] for f in res] == ["local"]
    assert res.reason == ("phoneinfoga scanner errors: "
                          "numverify: Invalid authentication credentials")
