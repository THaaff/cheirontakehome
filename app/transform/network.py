"""Co-occurrence network construction with networkx (the rubric's differentiator).

Three network shapes are supported, selected by ``plan.network.node_types`` and
``edge_semantics``:

* **bipartite** ``[sponsor, drug]`` — a node per distinct lead sponsor and per
  distinct drug; an edge whenever a trial has both, weighted by the number of
  such trials.
* **drug-drug** ``[drug]`` — a node per distinct drug; an edge between two drugs
  that co-occur in the same trial, weighted by the co-occurrence trial count.
* **sponsor-sponsor** ``[sponsor]`` (``shared_drug``) — a node per distinct lead
  sponsor; an edge between two sponsors that each ran a trial on the same drug,
  weighted by the number of drugs they share. A trial has exactly one lead
  sponsor, so sponsors never co-occur *within* a trial; the shared drug is what
  connects them, and it is the edge's provenance.

``min_edge_weight`` prunes weak edges; the graph is then capped to the top
``max_nodes`` by node weight (the number of distinct trials a node participates
in). With ``precompute_layout`` we run ``spring_layout`` server-side and stamp
``x``/``y`` on every node. Every node and edge carries the contributing NCT ids
as provenance.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import networkx as nx  # type: ignore[import-untyped]

from app.contracts import (
    AnalysisPlan,
    Citation,
    GraphData,
    GraphEdge,
    GraphNode,
    InterventionType,
    NetworkSpec,
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

# Intermediate accumulators shared by every shape before assembly.
_NodeTrials = dict[str, dict[str, StudyRecord]]
_Edge = tuple[str, str]


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
    drug_drug = node_types == {NodeType.drug}
    sponsor_sponsor = node_types == {NodeType.sponsor}

    if not studies:
        return GraphData(warnings=["no studies to aggregate; empty network"])
    if not (bipartite or drug_drug or sponsor_sponsor):
        return GraphData(
            warnings=[
                "unsupported node_types "
                f"{[t.value for t in spec.node_types]}; expected [sponsor, drug], [drug], "
                "or [sponsor]"
            ]
        )

    if sponsor_sponsor:
        return _build_shared_drug_sponsor_network(studies, spec)
    return _build_co_occurrence_network(studies, spec, bipartite=bipartite)


# ---------------------------------------------------------------------------
# co-occurrence-in-trial shapes (bipartite sponsor↔drug, or drug↔drug)
# ---------------------------------------------------------------------------


def _build_co_occurrence_network(
    studies: list[StudyRecord], spec: NetworkSpec, *, bipartite: bool
) -> GraphData:
    node_label: dict[str, str] = {}
    node_kind: dict[str, NodeType] = {}
    node_trials: _NodeTrials = {}
    edge_trials: dict[_Edge, dict[str, StudyRecord]] = {}

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

    edge_weight = {key: len(trials) for key, trials in edge_trials.items()}

    def edge_citation(key: _Edge) -> list[Citation]:
        a, b = key
        field = _edge_field((node_kind[a], node_kind[b]))
        excerpt = f"{node_label[a]} + {node_label[b]}"
        return [make_citation(s, excerpt=excerpt, field=field) for s in edge_trials[key].values()]

    return _assemble_graph(
        node_label=node_label,
        node_kind=node_kind,
        node_trials=node_trials,
        edge_weight=edge_weight,
        edge_citation=edge_citation,
        spec=spec,
    )


# ---------------------------------------------------------------------------
# sponsor↔sponsor shape (linked by a drug both sponsors studied)
# ---------------------------------------------------------------------------


def _build_shared_drug_sponsor_network(
    studies: list[StudyRecord], spec: NetworkSpec
) -> GraphData:
    node_label: dict[str, str] = {}
    node_kind: dict[str, NodeType] = {}
    node_trials: _NodeTrials = {}
    drug_label: dict[str, str] = {}
    # drug_id -> sponsor_id -> {nct: study}: which sponsors ran each drug.
    drug_sponsors: dict[str, dict[str, dict[str, StudyRecord]]] = {}

    for study in studies:
        sponsor_name = study.lead_sponsor_name
        drugs = _drug_names(study)
        if not sponsor_name or not drugs:
            continue
        sponsor_id = f"sponsor:{_slugify(sponsor_name)}"
        node_label.setdefault(sponsor_id, sponsor_name)
        node_kind.setdefault(sponsor_id, NodeType.sponsor)
        node_trials.setdefault(sponsor_id, {})[study.nct_id] = study
        for name in drugs:
            drug_id = f"drug:{_slugify(name)}"
            drug_label.setdefault(drug_id, name)
            drug_sponsors.setdefault(drug_id, {}).setdefault(sponsor_id, {})[study.nct_id] = study

    # An edge connects two sponsors per drug they share; the edge's supporting
    # trials (per shared drug) are the union of each sponsor's trials on it.
    edge_drugs: dict[_Edge, dict[str, dict[str, StudyRecord]]] = {}
    for drug_id, sponsors in drug_sponsors.items():
        sponsor_ids = sorted(sponsors)
        for i in range(len(sponsor_ids)):
            for j in range(i + 1, len(sponsor_ids)):
                key = (sponsor_ids[i], sponsor_ids[j])
                edge_drugs.setdefault(key, {})[drug_id] = {
                    **sponsors[sponsor_ids[i]],
                    **sponsors[sponsor_ids[j]],
                }

    if not edge_drugs:
        return GraphData(warnings=["no sponsors shared a drug; empty network"])

    edge_weight = {key: len(drugs) for key, drugs in edge_drugs.items()}

    def edge_citation(key: _Edge) -> list[Citation]:
        return [
            make_citation(study, excerpt=drug_label[drug_id], field=FIELD_INTERVENTION_NAME)
            for drug_id, trials in edge_drugs[key].items()
            for study in trials.values()
        ]

    return _assemble_graph(
        node_label=node_label,
        node_kind=node_kind,
        node_trials=node_trials,
        edge_weight=edge_weight,
        edge_citation=edge_citation,
        spec=spec,
    )


# ---------------------------------------------------------------------------
# shared assembly: prune -> cap -> layout -> emit
# ---------------------------------------------------------------------------


def _assemble_graph(
    *,
    node_label: dict[str, str],
    node_kind: dict[str, NodeType],
    node_trials: _NodeTrials,
    edge_weight: dict[_Edge, int],
    edge_citation: Callable[[_Edge], list[Citation]],
    spec: NetworkSpec,
) -> GraphData:
    """Prune weak edges, cap to ``max_nodes``, lay out, and emit nodes/edges.

    ``edge_citation`` is called only for surviving edges (cheap on large graphs).
    Node/edge weight both encode "how much": trial participation for a node, and
    the shape-specific edge weight (trial count, or shared-drug count) for edges.
    """
    surviving = {key: w for key, w in edge_weight.items() if w >= spec.min_edge_weight}
    candidate_ids = {nid for key in surviving for nid in key}
    kept_ids = set(
        sorted(candidate_ids, key=lambda nid: (-len(node_trials[nid]), nid))[: spec.max_nodes]
    )
    kept_edges = {
        key: w for key, w in surviving.items() if key[0] in kept_ids and key[1] in kept_ids
    }
    # A node kept only via an edge whose other endpoint was capped out can become
    # isolated; drop such isolated nodes so the rendered graph stays meaningful.
    connected_ids = {nid for key in kept_edges for nid in key}

    if not connected_ids:
        return GraphData(
            warnings=[
                f"no co-occurrences met min_edge_weight={spec.min_edge_weight}; empty network"
            ]
        )

    graph = nx.Graph()
    for nid in connected_ids:
        graph.add_node(nid)
    for key, weight in kept_edges.items():
        graph.add_edge(key[0], key[1], weight=float(weight))

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
    for key, weight in sorted(kept_edges.items(), key=lambda kv: (-kv[1], kv[0])):
        edges.append(
            GraphEdge(
                source=key[0],
                target=key[1],
                weight=float(weight),
                citations=edge_citation(key),
            )
        )

    return GraphData(nodes=nodes, edges=edges, warnings=[])
