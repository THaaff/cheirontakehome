"""cooccurrence_network: nodes/edges/weights, min_edge_weight, max_nodes, layout, provenance."""

from __future__ import annotations

from app.contracts import (
    AnalysisPlan,
    EdgeSemantics,
    InterventionType,
    NetworkSpec,
    NodeType,
    Operation,
    StudyRecord,
)
from app.transform import build_cooccurrence_network


def _net_plan(spec: NetworkSpec) -> AnalysisPlan:
    return AnalysisPlan(
        operation=Operation.cooccurrence_network,
        network=spec,
        proposed_viz="network_graph",
        interpretation="co-occurrence network",
    )


def _trial(nct: str, sponsor: str, drugs: list[str]) -> StudyRecord:
    return StudyRecord(
        nct_id=nct,
        lead_sponsor_name=sponsor,
        intervention_names=drugs,
        intervention_types=[InterventionType.DRUG] * len(drugs),
    )


# --- fixture-based structural tests -----------------------------------------


def test_bipartite_fixture_structure_and_provenance(studies: list[StudyRecord]) -> None:
    spec = NetworkSpec(node_types=[NodeType.sponsor, NodeType.drug], min_edge_weight=1)
    graph = build_cooccurrence_network(studies, _net_plan(spec))

    pembro = next((n for n in graph.nodes if n.id == "drug:pembrolizumab"), None)
    assert pembro is not None
    assert pembro.type is NodeType.drug
    assert pembro.weight == 9.0  # participates in 9 trials
    assert pembro.citations and len(pembro.citations) == 9  # one per contributing trial

    assert graph.edges
    # Bipartite: every edge connects one sponsor node to one drug node.
    ids = {n.id: n.type for n in graph.nodes}
    for edge in graph.edges:
        kinds = {ids[edge.source], ids[edge.target]}
        assert kinds == {NodeType.sponsor, NodeType.drug}
        assert edge.citations


def test_behavioral_intervention_is_not_a_drug_node(studies: list[StudyRecord]) -> None:
    spec = NetworkSpec(node_types=[NodeType.sponsor, NodeType.drug], min_edge_weight=1)
    graph = build_cooccurrence_network(studies, _net_plan(spec))
    labels = {n.label for n in graph.nodes}
    # "Structured lifestyle intervention" is BEHAVIORAL, not DRUG/BIOLOGICAL.
    assert "Structured lifestyle intervention" not in labels


def test_precompute_layout_toggles_coordinates(studies: list[StudyRecord]) -> None:
    on = build_cooccurrence_network(
        studies,
        _net_plan(
            NetworkSpec(node_types=[NodeType.sponsor, NodeType.drug], precompute_layout=True)
        ),
    )
    assert all(n.x is not None and n.y is not None for n in on.nodes)

    off = build_cooccurrence_network(
        studies,
        _net_plan(
            NetworkSpec(node_types=[NodeType.sponsor, NodeType.drug], precompute_layout=False)
        ),
    )
    assert all(n.x is None and n.y is None for n in off.nodes)


# --- synthetic weighted tests -----------------------------------------------


def test_min_edge_weight_drops_weak_edges() -> None:
    trials = [
        _trial("NCT00000001", "MegaPharma", ["DrugA"]),
        _trial("NCT00000002", "MegaPharma", ["DrugA"]),
        _trial("NCT00000003", "MegaPharma", ["DrugA"]),  # MegaPharma–DrugA weight 3
        _trial("NCT00000004", "MegaPharma", ["DrugB"]),  # MegaPharma–DrugB weight 1
    ]
    spec = NetworkSpec(node_types=[NodeType.sponsor, NodeType.drug], min_edge_weight=2)
    graph = build_cooccurrence_network(trials, _net_plan(spec))

    assert all(e.weight >= 2 for e in graph.edges)
    assert all(e.weight != 1 for e in graph.edges)
    # The weight-1 DrugB edge is gone, so DrugB is no longer a node.
    assert "drug:drugb" not in {n.id for n in graph.nodes}
    edge = next(e for e in graph.edges)
    assert edge.weight == 3.0


def test_max_nodes_cap() -> None:
    # One shared sponsor + one shared "Core" drug across 5 trials, plus a unique drug each.
    trials = [
        _trial(f"NCT0000010{i}", "Spon", [f"Drug{i}", "Core"]) for i in range(5)
    ]
    spec = NetworkSpec(node_types=[NodeType.sponsor, NodeType.drug], min_edge_weight=1, max_nodes=2)
    graph = build_cooccurrence_network(trials, _net_plan(spec))
    assert len(graph.nodes) <= 2


def test_drug_drug_co_occurrence_weights() -> None:
    trials = [
        _trial("NCT00000001", "S1", ["DrugA", "DrugB"]),
        _trial("NCT00000002", "S2", ["DrugA", "DrugB"]),  # A–B weight 2
        _trial("NCT00000003", "S3", ["DrugA", "DrugC"]),  # A–C weight 1
    ]
    spec = NetworkSpec(node_types=[NodeType.drug], min_edge_weight=2)
    graph = build_cooccurrence_network(trials, _net_plan(spec))
    assert len(graph.edges) == 1
    assert graph.edges[0].weight == 2.0
    # Only drugs remain; DrugC (weight-1 edge) is dropped.
    assert {n.id for n in graph.nodes} == {"drug:druga", "drug:drugb"}
    assert all(n.type is NodeType.drug for n in graph.nodes)


def test_empty_input_is_safe() -> None:
    spec = NetworkSpec(node_types=[NodeType.sponsor, NodeType.drug])
    graph = build_cooccurrence_network([], _net_plan(spec))
    assert graph.nodes == [] and graph.edges == []
    assert graph.warnings


# --- sponsor-sponsor shared-drug shape --------------------------------------


def _sponsor_net_spec(**kwargs: object) -> NetworkSpec:
    return NetworkSpec(
        node_types=[NodeType.sponsor],
        edge_semantics=EdgeSemantics.shared_drug,
        **kwargs,  # type: ignore[arg-type]
    )


def test_sponsor_sponsor_edge_weight_is_shared_drug_count() -> None:
    # Merck and Pfizer both run trials on DrugA and DrugB (2 shared drugs);
    # Roche shares only DrugA with each of them (weight 1).
    trials = [
        _trial("NCT00000001", "Merck", ["DrugA"]),
        _trial("NCT00000002", "Merck", ["DrugB"]),
        _trial("NCT00000003", "Pfizer", ["DrugA", "DrugB"]),
        _trial("NCT00000004", "Roche", ["DrugA"]),
    ]
    graph = build_cooccurrence_network(trials, _net_plan(_sponsor_net_spec()))

    # Every node is a sponsor; drugs are the connective evidence, not nodes.
    assert graph.nodes and all(n.type is NodeType.sponsor for n in graph.nodes)
    assert {n.id for n in graph.nodes} == {"sponsor:merck", "sponsor:pfizer", "sponsor:roche"}

    def weight(a: str, b: str) -> float:
        lo, hi = sorted((a, b))
        return next(e.weight for e in graph.edges if (e.source, e.target) == (lo, hi))

    assert weight("sponsor:merck", "sponsor:pfizer") == 2.0  # DrugA + DrugB
    assert weight("sponsor:merck", "sponsor:roche") == 1.0  # DrugA only
    # Edge provenance cites the shared drug from both sponsors' trials.
    merck_pfizer = next(
        e for e in graph.edges if {e.source, e.target} == {"sponsor:merck", "sponsor:pfizer"}
    )
    assert {c.nct_id for c in merck_pfizer.citations} >= {"NCT00000001", "NCT00000003"}


def test_sponsor_sponsor_min_edge_weight_prunes_by_shared_drugs() -> None:
    trials = [
        _trial("NCT00000001", "Merck", ["DrugA", "DrugB"]),
        _trial("NCT00000002", "Pfizer", ["DrugA", "DrugB"]),  # Merck–Pfizer share 2
        _trial("NCT00000003", "Roche", ["DrugA"]),  # Roche shares only 1 with each
    ]
    graph = build_cooccurrence_network(trials, _net_plan(_sponsor_net_spec(min_edge_weight=2)))
    assert {n.id for n in graph.nodes} == {"sponsor:merck", "sponsor:pfizer"}
    assert len(graph.edges) == 1 and graph.edges[0].weight == 2.0


def test_sponsor_sponsor_no_shared_drug_is_empty() -> None:
    trials = [
        _trial("NCT00000001", "Merck", ["DrugA"]),
        _trial("NCT00000002", "Pfizer", ["DrugB"]),  # no overlap
    ]
    graph = build_cooccurrence_network(trials, _net_plan(_sponsor_net_spec()))
    assert graph.nodes == [] and graph.edges == []
    assert graph.warnings
