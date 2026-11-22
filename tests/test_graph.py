"""Tests for the entity-resolution / link-analysis graph (build_graph)."""

from __future__ import annotations

from harrier.graph import build_graph, to_cypher, to_graphml
from harrier.schema import Finding, Provenance


def _findings():
    return [
        Finding(selector="awademan", source_tool="sherlock",
                url="https://github.com/awademan", value="https://github.com/awademan",
                confidence="medium", distinctiveness=0.9,
                provenance=Provenance(source_url="https://github.com/awademan",
                                      method="sherlock", content_hash="abc")),
        # duplicate entity from a second tool — must NOT create a second node
        Finding(selector="awademan", source_tool="maigret",
                url="https://github.com/awademan", value="https://github.com/awademan",
                confidence="high"),
        Finding(selector="+14025551234", source_tool="phoneinfoga",
                value="+14025551234", confidence="low"),
        Finding(selector="Amanda Bennett", source_tool="courtlistener",
                url="https://courtlistener.com/docket/1/", value="In re Amanda Bennett",
                confidence="low"),
        # blocked/keyless finding — no confirmed entity, must be skipped
        Finding(selector="Amanda Bennett", source_tool="people_search",
                value=None, url=None, tier="blocked"),
    ]


def test_build_graph_shapes_person_centered_network():
    g = build_graph(_findings(), {"name": "Amanda Bennett", "state": "NE"})
    ids = {n["id"] for n in g["nodes"]}
    # person node + account + phone + case (blocked skipped, dup collapsed)
    assert "person:amanda bennett" in ids
    assert any(n["type"] == "account" for n in g["nodes"])
    assert any(n["type"] == "phone" for n in g["nodes"])
    assert any(n["type"] == "case" for n in g["nodes"])
    assert g["stats"]["nodes"] == 4  # person + 3 entities
    # every edge originates at the person
    assert all(e["source"] == "person:amanda bennett" for e in g["edges"])


def test_duplicate_entity_collapses_and_keeps_best_confidence():
    g = build_graph(_findings(), {"name": "Amanda Bennett"})
    acct = [n for n in g["nodes"] if n["type"] == "account"]
    assert len(acct) == 1  # sherlock + maigret hit → one node
    # highest confidence across the two duplicate hits survives
    assert acct[0]["attrs"]["confidence"] == "high"


def test_edges_carry_weight_and_provenance():
    g = build_graph(_findings(), {"name": "Amanda Bennett"})
    acct_edge = next(e for e in g["edges"] if e["target"].startswith("account:"))
    assert acct_edge["relation"] == "has_account"
    # sherlock+maigret both found it → strongest weight, both methods, provenance kept
    assert acct_edge["weight"] == 1.0
    assert set(acct_edge["methods"]) == {"sherlock", "maigret"}
    assert acct_edge["provenance"]["content_hash"] == "abc"


def test_build_graph_empty_is_safe():
    g = build_graph([], {"name": "Nobody"})
    assert g["stats"]["nodes"] == 1  # just the person
    assert g["edges"] == []


def test_graphml_export_is_wellformed_xml():
    import xml.dom.minidom as minidom
    g = build_graph(_findings(), {"name": "Amanda Bennett"})
    xml = to_graphml(g)
    minidom.parseString(xml)  # raises if malformed
    assert "<graphml" in xml and "has_account" in xml


def test_cypher_export_merges_person_and_edges():
    g = build_graph(_findings(), {"name": "Amanda Bennett"})
    cy = to_cypher(g)
    assert "MERGE" in cy
    assert ":Person" in cy
    assert "HAS_ACCOUNT" in cy


def test_cypher_escapes_quotes():
    g = build_graph(
        [Finding(selector="x", source_tool="courtlistener",
                 value="O'Brien v. State", url="https://c/1")],
        {"name": "O'Brien"})
    cy = to_cypher(g)
    assert "\\'" in cy  # apostrophes escaped, not raw


def test_non_finite_distinctiveness_does_not_reach_the_exports():
    # Caller-supplied findings can carry NaN/inf (pydantic accepts them). The
    # Cypher export already neutralised it (C17); GraphML wrote "nan", which
    # is not an xsd:double (Gephi/Java reject it), and the JSON graph carried
    # NaN, which is not JSON.
    import json
    import math

    for bad in (float("nan"), float("inf")):
        f = Finding(selector="a", source_tool="maigret", url="https://x/a",
                    value="https://x/a", confidence="medium", distinctiveness=bad)
        g = build_graph([f], {"name": "Jane Doe"})
        (edge,) = g["edges"]
        assert math.isfinite(edge["weight"]) and edge["weight"] == 0.6
        assert '<data key="e_weight">0.6</data>' in to_graphml(g)
        json.dumps(g, allow_nan=False)
