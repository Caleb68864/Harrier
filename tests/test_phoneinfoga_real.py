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
    assert res.status == "ok"
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
    assert res.reason.startswith("phoneinfoga scanner errors: "
                                 "numverify: Invalid authentication credentials")


# `phoneinfoga scan -n +33142685300` (googlesearch block left out): ovh runs
# for French numbers and printed a negative.
_REAL_SCAN_OVH_NOT_FOUND = (
    "Running scan for phone number +33142685300...\n"
    "\n"
    "Results for local\n"
    "Raw local: 0142685300\n"
    "Local: 01 42 68 53 00\n"
    "E164: +33142685300\n"
    "International: 33142685300\n"
    "Country: FR\n"
    "\n"
    "Results for ovh\n"
    "Found: false\n"
    "\n"
    "2 scanner(s) succeeded\n"
)


def test_ovh_not_found_is_not_a_finding(monkeypatch):
    res = _run(monkeypatch, _REAL_SCAN_OVH_NOT_FOUND)
    assert res.status == "ok"
    assert [f.raw["scanner"] for f in res] == ["local"]


def test_ovh_found_is_a_finding(monkeypatch):
    out = _REAL_SCAN_OVH_NOT_FOUND.replace(
        "Found: false\n", "Found: true\nNumber range: 0142685xxx\nCity: Paris\n")
    res = _run(monkeypatch, out)
    assert sorted(f.raw["scanner"] for f in res) == ["local", "ovh"]


def test_only_a_negative_is_empty(monkeypatch):
    out = ("Running scan for phone number +33142685300...\n\n"
           "Results for ovh\nFound: false\n\n1 scanner(s) succeeded\n")
    res = _run(monkeypatch, out)
    assert res.status == "empty" and res == []


def test_keyless_run_says_which_keyed_scanners_were_skipped(monkeypatch):
    # PhoneInfoga skips numverify and googlecse without a key and prints
    # nothing about it (DryRun fails; logged at debug only).
    res = _run(monkeypatch, _REAL_SCAN)
    assert res.status == "ok"
    assert "numverify not run" in res.reason
    assert "NUMVERIFY_API_KEY" in res.reason
    assert "googlecse not run" in res.reason
    assert "GOOGLECSE_CX" in res.reason and "GOOGLE_API_KEY" in res.reason


def test_scanner_that_errored_is_not_called_skipped(monkeypatch):
    res = _run(monkeypatch, _REAL_SCAN_WITH_ERROR)
    assert "numverify not run" not in res.reason
    assert "numverify: Invalid authentication credentials" in res.reason
