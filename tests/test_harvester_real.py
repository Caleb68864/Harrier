"""O27: the domain adapter against a real theHarvester 4.11.1 report.

Captured 2026-11-21: theHarvester 4.11.1 (GitHub tag tarball, installed in a
scratch venv) run exactly as the adapter runs it (``-d kernel.org -b <the 11
FREE_SOURCES> -f report``). Exit 0 in 83 s; all 11 sources were searched with
no error. Lists are cut down; entries are as the tool wrote them.

Without ``-r``, theHarvester's ``hosts`` mixes bare hostnames with
``host:address`` pairs that a source reported (``__main__.py`` builds them as
``subdomain + ':' + addr``); the address is an IP (v4 or v6) or a CNAME.
"""

import json

from harrier.adapters import domain

_REAL_REPORT = {
    "asns": ["AS13335", "AS16276"],
    "cmd": "-d kernel.org -b ... -f report",
    "hosts": [
        "1vger.kernel.org",
        "alex.kernel.org",
        "ams.mirrors.kernel.org",
        "ams.mirrors.kernel.org:213.196.21.55",
        "ams.mirrors.kernel.org:2a01:60a::1994:3:14",
        "apparmor.wiki.kernel.org",
        "apparmor.wiki.kernel.org:korg-mediawiki-prod.eba-ntb3jmid.us-west-2.elasticbeanstalk.com",
        "archive.kernel.org",
        "archive.kernel.org:199.204.44.194",
        "archive.kernel.org:yul.archive.kernel.org",
    ],
    "interesting_urls": ["https://archive.kernel.org/", "https://git.kernel.org/"],
    "ips": ["104.21.35.72", "104.21.79.192", "141.94.157.2"],
    "shodan": [],
}


def _parse(tmp_path, report=_REAL_REPORT):
    (tmp_path / "report.json").write_text(json.dumps(report), encoding="utf-8")
    return domain._parse_report(str(tmp_path), "kernel.org")


def test_host_address_pairs_become_one_host_each(tmp_path):
    findings = _parse(tmp_path)
    hosts = [f.value for f in findings if f.raw["type"] == "host"]
    # One finding per hostname; "host:1.2.3.4" is not a hostname.
    assert hosts == ["1vger.kernel.org", "alex.kernel.org", "ams.mirrors.kernel.org",
                     "apparmor.wiki.kernel.org", "archive.kernel.org"]
    by_host = {f.value: f for f in findings}
    # The address a source reported is kept, IPv6 included (split on the
    # first colon only: a hostname has none).
    assert by_host["ams.mirrors.kernel.org"].raw["addresses"] == [
        "213.196.21.55", "2a01:60a::1994:3:14"]
    assert by_host["archive.kernel.org"].raw["addresses"] == [
        "199.204.44.194", "yul.archive.kernel.org"]
    assert "addresses" not in by_host["alex.kernel.org"].raw


def test_pair_without_bare_host_still_yields_the_host(tmp_path):
    findings = _parse(tmp_path, {"hosts": ["mail.example.com:192.0.2.1"]})
    assert [(f.value, f.raw["addresses"]) for f in findings] == [
        ("mail.example.com", ["192.0.2.1"])]


def test_report_without_emails_key_is_fine(tmp_path):
    # 4.11.1 leaves "emails" out when it found none (json_dict['emails'] is
    # set only if all_emails is non-empty).
    assert "emails" not in _REAL_REPORT
    assert all(f.raw["type"] == "host" for f in _parse(tmp_path))
