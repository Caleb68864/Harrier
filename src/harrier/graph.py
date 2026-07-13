"""Entity-resolution / link-analysis graph (build_graph).

The gap the OSINT-MCP ecosystem leaves open: everyone tool-chains selectors
(username → email → domain) inside the agent, but nobody emits the **graph**.
This turns a flat set of correlated findings into a nodes+edges network centered
on the target — the same "map all connections" artifact a Maltego/CoAnalyst360
user expects — with **provenance and a distinctiveness-weighted confidence on
every edge**, and exporters to GraphML and Neo4j Cypher.

Deterministic and pure: no network, no LLM. It arranges what collection already
found; the "is this really them?" call still belongs to the analyst.
"""

from __future__ import annotations

import re
from typing import Any

from harrier.schema import Finding

# source_tool -> (node_type, relation). theHarvester is split by raw payload type.
_ENTITY_MAP: dict[str, tuple[str, str]] = {
    "sherlock": ("account", "has_account"),
    "maigret": ("account", "has_account"),
    "holehe": ("account", "account_registered"),
    "socialscan": ("account", "account_registered"),
    "phoneinfoga": ("phone", "has_phone"),
    "courtlistener": ("case", "party_to_case"),
    "familysearch": ("record", "appears_in_record"),
    "people_search": ("lead", "possible_record"),
}

_CONF_WEIGHT = {"high": 1.0, "medium": 0.6, "low": 0.3}


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def _classify(f: Finding) -> tuple[str, str]:
    if f.source_tool == "theHarvester":
        if (f.raw or {}).get("type") == "host":
            return ("host", "resolves_host")
        return ("email", "has_email")
    return _ENTITY_MAP.get(f.source_tool, ("entity", "related_to"))


def _entity_value(f: Finding) -> str | None:
    # NOT selector — that's the query (often the person's own name), not a
    # discovered entity. A keyless/blocked finding has no entity to place.
    return f.value or f.url or None


def _edge_weight(f: Finding) -> float:
    if f.distinctiveness is not None:
        return round(float(f.distinctiveness), 2)
    return _CONF_WEIGHT.get(f.confidence, 0.3)


def build_graph(findings: list[Finding], anchor: dict | None = None) -> dict:
    """Build a person-centered entity graph from findings. Pure; never raises.

    Returns ``{"nodes": [...], "edges": [...], "stats": {...}}``. Each node has
    ``id/type/label/attrs``; each edge ``source/target/relation/weight`` plus
    provenance + confidence carried from the finding. Nodes and edges are
    de-duplicated; the strongest (highest-weight) edge/node survivor is kept.
    """
    anchor = anchor or {}
    name = anchor.get("name") or "target"
    person_id = "person:" + _norm(name)

    nodes: dict[str, dict] = {
        person_id: {
            "id": person_id, "type": "person", "label": name,
            "attrs": {k: v for k, v in anchor.items() if v},
        }
    }
    edges: dict[tuple, dict] = {}
    types: dict[str, int] = {}

    for f in findings or []:
        val = _entity_value(f)
        if not val:
            continue  # blocked/keyless finding — no confirmed entity to place
        ntype, relation = _classify(f)
        nid = f"{ntype}:{_norm(val)}"
        weight = _edge_weight(f)

        node = nodes.get(nid)
        node_attrs = {
            "tier": f.tier, "confidence": f.confidence,
            "likelihood": f.likelihood, "distinctiveness": f.distinctiveness,
            "platform": (f.raw or {}).get("site"),
        }
        if node is None:
            nodes[nid] = {"id": nid, "type": ntype, "label": val,
                          "attrs": {k: v for k, v in node_attrs.items() if v is not None}}
            types[ntype] = types.get(ntype, 0) + 1
        else:
            # keep the most informative confidence on repeated hits
            if _CONF_WEIGHT.get(f.confidence, 0) > _CONF_WEIGHT.get(
                    node["attrs"].get("confidence", "low"), 0):
                node["attrs"]["confidence"] = f.confidence

        prov = f.provenance.model_dump() if f.provenance else None
        ekey = (person_id, nid, relation)
        prev = edges.get(ekey)
        if prev is None:
            edges[ekey] = {
                "source": person_id, "target": nid, "relation": relation,
                "weight": weight, "source_tool": f.source_tool,
                "methods": [f.source_tool], "provenance": prov,
                "confidence": f.confidence, "likelihood": f.likelihood,
            }
        else:
            # Same link found by another tool — merge: strongest weight wins,
            # record every contributing method, and never drop provenance.
            prev["weight"] = max(prev["weight"], weight)
            if f.source_tool not in prev["methods"]:
                prev["methods"].append(f.source_tool)
            if not prev.get("provenance") and prov:
                prev["provenance"] = prov
            if _CONF_WEIGHT.get(f.confidence, 0) > _CONF_WEIGHT.get(prev["confidence"], 0):
                prev["confidence"] = f.confidence
            prev["likelihood"] = prev["likelihood"] or f.likelihood

    node_list = list(nodes.values())
    edge_list = list(edges.values())
    stats = {
        "nodes": len(node_list), "edges": len(edge_list),
        "entity_types": types, "target": name,
    }
    return {"nodes": node_list, "edges": edge_list, "stats": stats}


# --- exporters ---------------------------------------------------------------

def _xml_escape(s: Any) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def to_graphml(graph: dict) -> str:
    """Serialize a graph to GraphML (opens in Gephi/yEd/Cytoscape)."""
    keys = [
        ('d_type', 'node', 'type', 'string'),
        ('d_label', 'node', 'label', 'string'),
        ('d_conf', 'node', 'confidence', 'string'),
        ('e_rel', 'edge', 'relation', 'string'),
        ('e_weight', 'edge', 'weight', 'double'),
        ('e_method', 'edge', 'method', 'string'),
        ('e_src', 'edge', 'source_url', 'string'),
    ]
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">']
    for kid, dom, name, typ in keys:
        out.append(f'  <key id="{kid}" for="{dom}" attr.name="{name}" attr.type="{typ}"/>')
    out.append('  <graph edgedefault="directed">')
    for n in graph.get("nodes", []):
        out.append(f'    <node id="{_xml_escape(n["id"])}">')
        out.append(f'      <data key="d_type">{_xml_escape(n["type"])}</data>')
        out.append(f'      <data key="d_label">{_xml_escape(n["label"])}</data>')
        conf = n.get("attrs", {}).get("confidence")
        if conf:
            out.append(f'      <data key="d_conf">{_xml_escape(conf)}</data>')
        out.append('    </node>')
    for i, e in enumerate(graph.get("edges", [])):
        out.append(f'    <edge id="e{i}" source="{_xml_escape(e["source"])}" '
                   f'target="{_xml_escape(e["target"])}">')
        out.append(f'      <data key="e_rel">{_xml_escape(e["relation"])}</data>')
        out.append(f'      <data key="e_weight">{_xml_escape(e["weight"])}</data>')
        out.append(f'      <data key="e_method">{_xml_escape(e.get("source_tool") or "")}</data>')
        src = (e.get("provenance") or {}).get("source_url") or ""
        out.append(f'      <data key="e_src">{_xml_escape(src)}</data>')
        out.append('    </edge>')
    out.append('  </graph>')
    out.append('</graphml>')
    return "\n".join(out)


def _cy(s: Any) -> str:
    return str(s).replace("\\", "\\\\").replace("'", "\\'")


def to_cypher(graph: dict) -> str:
    """Serialize a graph to Neo4j Cypher MERGE statements."""
    lines: list[str] = []
    idx: dict[str, str] = {}
    for i, n in enumerate(graph.get("nodes", [])):
        var = f"n{i}"
        idx[n["id"]] = var
        label = "".join(w.capitalize() for w in re.split(r"[^a-z0-9]+", n["type"]) if w) or "Entity"
        lines.append(
            f"MERGE ({var}:{label} {{id:'{_cy(n['id'])}'}}) "
            f"SET {var}.label='{_cy(n['label'])}';")
    for e in graph.get("edges", []):
        sv, tv = idx.get(e["source"]), idx.get(e["target"])
        if not sv or not tv:
            continue
        rel = re.sub(r"[^A-Z0-9_]", "", e["relation"].upper().replace(" ", "_")) or "RELATED_TO"
        method = _cy(e.get("source_tool") or "")
        lines.append(
            f"MATCH (a {{id:'{_cy(e['source'])}'}}),(b {{id:'{_cy(e['target'])}'}}) "
            f"MERGE (a)-[r:{rel}]->(b) SET r.weight={e['weight']}, r.method='{method}';")
    return "\n".join(lines)


def register(app) -> None:
    """Register the `build_graph` MCP tool."""

    @app.tool(name="build_graph")
    def build_graph_tool(
        name: str,
        city: str | None = None,
        state: str | None = None,
        maiden: str | None = None,
        married: str | None = None,
        nicknames: list[str] | None = None,
        email: str | None = None,
        phone: str | None = None,
        findings: list[dict] | None = None,
        depth: str = "quick",
        consent: bool = False,
    ) -> dict:
        """Build a provenance-stamped entity graph for a person.

        If ``findings`` (a list of Finding dicts from a prior sweep) is given, the
        graph is built from those — no new collection. Otherwise a verified
        ``person_sweep`` is run first. Returns the graph plus GraphML + Cypher
        exports and summary stats.
        """
        anchor = {"name": name, "city": city, "state": state,
                  "maiden": maiden, "married": married}
        if findings is not None:
            fs = [Finding(**d) for d in findings]
        else:
            from harrier import sweep as sweep_mod
            res = sweep_mod.person_sweep(
                name, city=city, state=state, maiden=maiden, married=married,
                nicknames=nicknames, email=email, phone=phone, depth=depth,
                verify=True, consent=consent)
            fs = res["findings"]
        graph = build_graph(fs, anchor)
        return {
            "graph": graph,
            "graphml": to_graphml(graph),
            "cypher": to_cypher(graph),
            "stats": graph["stats"],
        }
