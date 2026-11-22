"""Agent decisions, second batch (roadmap O26, O30, O31; 2026-11-21)."""

import harrier.investigate as inv
from harrier.correlate import correlate
from harrier.schema import Finding


# --- O26: dedupe by what was searched, not only by the value -----------------

def _holehe(email):
    return Finding(selector=email, source_tool="holehe", value="instagram", exists=True)


def test_correlate_keeps_same_value_from_different_selectors():
    out = correlate([_holehe("a@example.com"), _holehe("b@example.com")])
    assert sorted(f.selector for f in out) == ["a@example.com", "b@example.com"]
    assert {f.confidence for f in out} == {"low"}  # one family: no agreement


def test_correlate_still_drops_a_true_duplicate():
    out = correlate([_holehe("a@example.com"), _holehe("a@example.com")])
    assert len(out) == 1


def test_correlate_agreement_across_families_is_unchanged():
    a = Finding(selector="awademan", source_tool="sherlock", url="https://x/a",
                value="https://x/a")
    b = Finding(selector="Amanda Wademan", source_tool="courtlistener",
                value="https://x/a")
    assert {f.confidence for f in correlate([a, b])} == {"high"}


def test_investigate_dedup_keys_on_selector():
    out = inv._dedup([_holehe("a@example.com"), _holehe("b@example.com"),
                      _holehe("b@example.com")])
    assert sorted(f.selector for f in out) == ["a@example.com", "b@example.com"]


# --- O30: theHarvester gets a HOME Harrier owns --------------------------------
# 4.11.1 has no config-dir option: it writes ~/.theHarvester/{api-keys,proxies}.yaml
# (lib/core.py CONFIG_DIRS[0]) and a scan history of every domain searched to
# ~/.local/share/theHarvester/stash.sqlite (lib/stash.py), both via expanduser,
# i.e. $HOME.

import os  # noqa: E402
import subprocess  # noqa: E402

from harrier.adapters import domain, run_subprocess  # noqa: E402


def _harvest_env(monkeypatch, tmp_path):
    seen = {}

    def fake(args, timeout=30, env=None):
        seen["env"] = env
        seen["home_existed"] = env is not None and os.path.isdir(env.get("HOME", ""))
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(domain, "binary_available", lambda n: True)
    monkeypatch.setattr(domain, "run_subprocess", fake)
    domain.run("example.com")
    return seen


def test_harvester_runs_with_a_throwaway_home(monkeypatch, tmp_path):
    monkeypatch.delenv("HARRIER_HARVESTER_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "realhome"))
    seen = _harvest_env(monkeypatch, tmp_path)
    home = seen["env"]["HOME"]
    assert home != str(tmp_path / "realhome")
    assert seen["home_existed"]
    assert not os.path.exists(home)  # removed after the run, with the report
    assert seen["env"]["PATH"] == os.environ["PATH"]  # rest of env inherited


def test_harvester_home_setting_uses_that_dir(monkeypatch, tmp_path):
    keep = tmp_path / "harvester-home"
    monkeypatch.setenv("HARRIER_HARVESTER_HOME", str(keep))
    seen = _harvest_env(monkeypatch, tmp_path)
    assert seen["env"]["HOME"] == str(keep)
    assert keep.is_dir()  # created if missing, and kept


def test_run_subprocess_passes_env():
    out = run_subprocess(["sh", "-c", "printf %s \"$HOME\""], timeout=5,
                         env={**os.environ, "HOME": "/nonexistent-harrier"})
    assert out.stdout == "/nonexistent-harrier"


# --- O31: generate_candidates says why it returned nothing --------------------

import asyncio  # noqa: E402
import json  # noqa: E402

from harrier.server import create_app  # noqa: E402


def _call(args):
    async def go():
        return await create_app().call_tool("generate_candidates", args)

    res = asyncio.run(go())
    content = res[0] if isinstance(res, tuple) else res
    return content


def _texts(content):
    return [c.text for c in content]


def test_candidates_plain_call_is_unchanged():
    # Backward compatible: a valid call still returns the bare list.
    content = _call({"first": "Amanda", "last": "Wademan", "max": 3})
    texts = _texts(content)
    assert len(texts) == 3 and all(not t.startswith("{") for t in texts)


def test_candidates_bad_input_is_a_tool_error_with_a_reason():
    from mcp.server.fastmcp.exceptions import ToolError
    import pytest

    for args, why in (({"first": "", "last": " "}, "first or last name"),
                      ({"first": "Amanda", "last": "Wademan", "max": 0}, "max")):
        with pytest.raises(ToolError, match=why):
            _call(args)


def test_candidates_detailed_shape():
    (c,) = _call({"first": "Amanda", "last": "Wademan", "max": 2, "detailed": True})
    out = json.loads(c.text)
    assert out["status"] == "ok" and out["count"] == 2
    assert len(out["candidates"]) == 2 and out["reason"] is None
    (c,) = _call({"first": "", "last": "", "detailed": True})
    out = json.loads(c.text)
    assert out["status"] == "error" and out["candidates"] == []
    assert "first or last name" in out["reason"]
