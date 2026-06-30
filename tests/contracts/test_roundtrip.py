"""Round-trip: each top-level model serializes to JSON and re-parses equal (Section K)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from app.contracts import (
    AnalysisPlan,
    CategoricalField,
    Channel,
    ChartDatum,
    ChartVizSpec,
    Citation,
    DataPoint,
    Encoding,
    Entities,
    ErrorDetail,
    ErrorResponse,
    Filters,
    GraphData,
    GraphEdge,
    GraphNode,
    GraphVizSpec,
    Meta,
    NetworkSpec,
    Operation,
    PipelineStage,
    RequestOptions,
    RetrievalResult,
    SeriesSpec,
    StudyRecord,
    TidyDataset,
    VisualizationRequest,
    VisualizationResponse,
    VizType,
)


def _roundtrip(instance: BaseModel) -> None:
    """Assert ``instance`` survives a JSON dump/reload unchanged."""
    dumped = instance.model_dump_json()
    reparsed = type(instance).model_validate_json(dumped)
    assert reparsed == instance


def _chart_datum() -> ChartDatum:
    return ChartDatum.model_validate({"phase": "PHASE3", "trial_count": 78})


def _chart_spec() -> ChartVizSpec:
    return ChartVizSpec(
        renderer="vega-lite",
        type=VizType.bar_chart,
        title="Phases",
        encoding=Encoding(
            x=Channel(field="phase", type="nominal"),
            y=Channel(field="trial_count", type="quantitative"),
        ),
        data=[_chart_datum()],
        vega_spec={"mark": "bar"},
    )


def test_visualization_request_roundtrip() -> None:
    _roundtrip(
        VisualizationRequest(
            query="trials for pembrolizumab since 2018",
            drug_name="pembrolizumab",
            start_year=2018,
            options=RequestOptions(mode="replay", debug=True),
        )
    )


def test_analysis_plan_roundtrip() -> None:
    _roundtrip(
        AnalysisPlan(
            operation=Operation.comparison,
            entities=Entities(condition="melanoma"),
            filters=Filters(start_year=2018, end_year=2022),
            group_by=CategoricalField.lead_sponsor_class,
            series=SeriesSpec(dimension="condition", values=["melanoma", "lung cancer"]),
            proposed_viz=VizType.grouped_bar_chart,
            interpretation="compare sponsor mix",
        )
    )


def test_network_plan_roundtrip() -> None:
    _roundtrip(
        AnalysisPlan(
            operation=Operation.cooccurrence_network,
            network=NetworkSpec(node_types=["sponsor", "drug"], min_edge_weight=2),
            proposed_viz=VizType.network_graph,
            interpretation="network",
        )
    )


def test_tidy_dataset_roundtrip() -> None:
    _roundtrip(
        TidyDataset(
            points=[
                DataPoint(
                    dims={"year": 2021, "series": "melanoma"},
                    measure="trial_count",
                    value=84,
                    citations=[Citation(nct_id="NCT04895709", excerpt="2021-05-10")],
                )
            ],
            dimension_names=["year", "series"],
            measure_name="trial_count",
        )
    )


def test_graph_data_roundtrip() -> None:
    _roundtrip(
        GraphData(
            nodes=[
                GraphNode(
                    id="drug:p", label="Pembrolizumab", type="drug", weight=38.0, x=0.1, y=0.2
                )
            ],
            edges=[GraphEdge(source="drug:p", target="sponsor:m", weight=31.0)],
        )
    )


def test_chart_viz_spec_roundtrip() -> None:
    _roundtrip(_chart_spec())


def test_graph_viz_spec_roundtrip() -> None:
    _roundtrip(
        GraphVizSpec(
            title="Network",
            data=GraphData(
                nodes=[GraphNode(id="drug:p", label="Pembrolizumab", type="drug", weight=5.0)],
                edges=[GraphEdge(source="drug:p", target="sponsor:m", weight=3.0)],
            ),
            layout="force",
        )
    )


def test_visualization_response_roundtrip() -> None:
    _roundtrip(
        VisualizationResponse(
            request_id="3f2504e0-4f89-41d3-9a0c-0305e82c3301",
            visualization=_chart_spec(),
            meta=Meta(query_interpretation="distribution of phases", studies_analyzed=498),
        )
    )


def test_study_record_roundtrip() -> None:
    _roundtrip(
        StudyRecord(
            nct_id="NCT03240016",
            brief_title="Abraxane With Anti-PD1/PDL1",
            phases=["PHASE2"],
            overall_status="COMPLETED",
            study_type="INTERVENTIONAL",
            lead_sponsor_name="University of Michigan Rogel Cancer Center",
            lead_sponsor_class="OTHER",
            start_date=date(2018, 2, 8),
            start_date_raw="2018-02-08",
            completion_date=date(2022, 6, 30),
            intervention_types=["DRUG"],
            intervention_names=["Pembrolizumab"],
            conditions=["Urothelial Carcinoma"],
            countries=["United States"],
            enrollment_count=36,
        )
    )


def test_retrieval_result_roundtrip() -> None:
    _roundtrip(
        RetrievalResult(
            studies=[StudyRecord(nct_id="NCT03240016")],
            total_matched=2892,
            studies_analyzed=1,
            data_timestamp="2026-06-30T09:00:05",
            warnings=["1 study had an unparseable start date"],
        )
    )


def test_error_response_roundtrip() -> None:
    _roundtrip(
        ErrorResponse(
            request_id="3f2504e0-4f89-41d3-9a0c-0305e82c3301",
            error=ErrorDetail(
                type="upstream_unavailable",
                stage=PipelineStage.retrieval,
                message="ClinicalTrials.gov returned 503",
                details={"status_code": 503},
            ),
        )
    )
