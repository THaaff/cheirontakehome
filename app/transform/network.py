"""Co-occurrence network construction with networkx (the rubric's differentiator).

Two network shapes are supported, selected by ``plan.network.node_types``:

* **bipartite** ``[sponsor, drug]`` — a node per distinct lead sponsor and per
  distinct drug; an edge whenever a trial has both, weighted by the number of
  such trials.
* **drug-drug** ``[drug]`` — a node per distinct drug; an edge between two drugs
  that co-occur in the same trial, weighted by the co-occurrence trial count.

``min_edge_weight`` prunes weak edges; the graph is then capped to the top
``max_nodes`` by node weight (the number of distinct trials a node participates
in). With ``precompute_layout`` we run ``spring_layout`` server-side and stamp
``x``/``y`` on every node. Every node and edge carries the contributing NCT ids
as provenance.
"""

from __future__ import annotations

import re

import networkx as nx  # type: ignore[import-untyped]

from app.contracts import (
    AnalysisPlan,
    GraphData,
    GraphEdge,
    GraphNode,
    InterventionType,
    NodeType,
    StudyRecord,
)
from app.transform.provenance import (
    FIELD_INTERVENTION_NAME,
    FIELD_LEAD_SPONSOR_NAME,
    make_citation,
)

# Only confirmed therapeutic interventions become "drug" nodes. The name/type
# lists are positionally aligned (retrieval emits them in parallel), so we zip
# them and keep names whose aligned type is a drug or biologic.
_DRUG_TYPES = frozenset({InterventionType.DRUG, InterventionType.BIOLOGICAL})

_LAYOUT_SEED = 42


def _slugify(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    return slug or "node"


def _drug_names(study: StudyRecord) -> list[str]:
    """Distinct drug/biologic intervention names for a study (deduped, ordered)."""

    seen: set[str] = set()
    names: list[str] = []
    for name, itype in zip(study.intervention_names, study.intervention_types, strict=False):
        if itype in _DRUG_TYPES and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def _edge_field(types: tuple[NodeType, NodeType]) -> str:
    """The source field path to cite for an edge, by its endpoint types."""

    return FIELD_LEAD_SPONSOR_NAME if NodeType.sponsor in types else FIELD_INTERVENTION_NAME


def build_cooccurrence_network(studies: list[StudyRecord], plan: AnalysisPlan) -> GraphData:
    spec = plan.network
    if spec is None:
        raise ValueError("cooccurrence_network requires plan.network")

    node_types = set(spec.node_types)
    bipartite = NodeType.sponsor in node_types and NodeType.drug in node_types
    drug_drug = not bipartite and NodeType.drug in node_types

    if not studies:
        return GraphData(warnings=["no studies to aggregate; empty network"])
    if not (bipartite or drug_drug):
        return GraphData(
            warnings=[
                "unsupported node_types "
                f"{[t.value for t in spec.node_types]}; expected [sponsor, drug] or [drug]"
            ]
        )

    # --- accumulate nodes, per-node trial participation, and per-edge trials ---
    node_label: dict[str, str] = {}
    node_kind: dict[str, NodeType] = {}
    node_trials: dict[str, dict[str, StudyRecord]] = {}
    edge_trials: dict[tuple[str, str], dict[str, StudyRecord]] = {}

    def reg_node(node_id: str, label: str, kind: NodeType, study: StudyRecord) -> None:
        node_label.setdefault(node_id, label)
        node_kind.setdefault(node_id, kind)
        node_trials.setdefault(node_id, {})[study.nct_id] = study

    def reg_edge(a: str, b: str, study: StudyRecord) -> None:
        key = (a, b) if a <= b else (b, a)
        edge_trials.setdefault(key, {})[study.nct_id] = study

    for study in studies:
        drugs = [(f"drug:{_slugify(n)}", n) for n in _drug_names(study)]
        if bipartite:
            sponsor_name = study.lead_sponsor_name
            sponsor_id = f"sponsor:{_slugify(sponsor_name)}" if sponsor_name else None
            if sponsor_id is not None and sponsor_name is not None:
                reg_node(sponsor_id, sponsor_name, NodeType.sponsor, study)
            for drug_id, drug_name in drugs:
                reg_node(drug_id, drug_name, NodeType.drug, study)
                if sponsor_id is not None:
                    reg_edge(sponsor_id, drug_id, study)
        else:  # drug-drug
            for drug_id, drug_name in drugs:
                reg_node(drug_id, drug_name, NodeType.drug, study)
            for i in range(len(drugs)):
                for j in range(i + 1, len(drugs)):
                    if drugs[i][0] != drugs[j][0]:
                        reg_edge(drugs[i][0], drugs[j][0], study)

    # --- prune by min_edge_weight, then cap to max_nodes by node weight ---
    surviving_edges = {
        key: trials
        for key, trials in edge_trials.items()
        if len(trials) >= spec.min_edge_weight
    }
    candidate_ids = {nid for key in surviving_edges for nid in key}
    kept_ids = set(
        sorted(candidate_ids, key=lambda nid: (-len(node_trials[nid]), nid))[: spec.max_nodes]
    )
    kept_edges = {
        key: trials
        for key, trials in surviving_edges.items()
        if key[0] in kept_ids and key[1] in kept_ids
    }
    # A node kept only via an edge whose other endpoint was capped out can become
    # isolated; drop such isolated nodes so the rendered graph stays meaningful.
    connected_ids = {nid for key in kept_edges for nid in key}

    warnings: list[str] = []
    if not connected_ids:
        warnings.append(
            f"no co-occurrences met min_edge_weight={spec.min_edge_weight}; empty network"
        )
        return GraphData(warnings=warnings)

    # --- build the networkx graph (canonical structure + optional layout) ---
    graph = nx.Graph()
    for nid in connected_ids:
        graph.add_node(nid)
    for key, trials in kept_edges.items():
        graph.add_edge(key[0], key[1], weight=float(len(trials)))

    positions: dict[str, tuple[float, float]] = {}
    if spec.precompute_layout:
        pos = nx.spring_layout(graph, seed=_LAYOUT_SEED, weight="weight")
        positions = {str(nid): (float(xy[0]), float(xy[1])) for nid, xy in pos.items()}

    nodes: list[GraphNode] = []
    for nid in sorted(connected_ids, key=lambda nid: (-len(node_trials[nid]), nid)):
        kind = node_kind[nid]
        label = node_label[nid]
        field = FIELD_LEAD_SPONSOR_NAME if kind is NodeType.sponsor else FIELD_INTERVENTION_NAME
        citations = [
            make_citation(s, excerpt=label, field=field) for s in node_trials[nid].values()
        ]
        x, y = positions.get(nid, (None, None))
        nodes.append(
            GraphNode(
                id=nid,
                label=label,
                type=kind,
                weight=float(len(node_trials[nid])),
                x=x,
                y=y,
                citations=citations,
            )
        )

    edges: list[GraphEdge] = []
    for key, trials in sorted(kept_edges.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        a, b = key
        field = _edge_field((node_kind[a], node_kind[b]))
        excerpt = f"{node_label[a]} + {node_label[b]}"
        citations = [make_citation(s, excerpt=excerpt, field=field) for s in trials.values()]
        edges.append(
            GraphEdge(source=a, target=b, weight=float(len(trials)), citations=citations)
        )

    return GraphData(nodes=nodes, edges=edges, warnings=warnings)
