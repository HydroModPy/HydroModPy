"""Regional basin-site selection helpers."""

from __future__ import annotations

from hydromodpy.spatial.site_selection.candidates.generation import (
    CandidateGenerationEvidence,
    candidate_generation_evidence_with_candidate_attributes,
    generate_network_candidate_outlets,
    write_generated_network_geojson,
)
from hydromodpy.spatial.site_selection.candidates.outlets import (
    CandidateOutlet,
    candidate_outlets_from_point_records,
    candidate_outlets_from_rows,
    thin_candidate_outlets,
)
from hydromodpy.spatial.site_selection.candidates.pipeline import (
    GeneratedCandidateResult,
    build_dem_area_light_candidates,
    build_generated_network_candidates,
    build_station_candidate_outlets,
    site_selection_search_geometry,
)
from hydromodpy.spatial.site_selection.config import SiteSelectionConfig
from hydromodpy.spatial.site_selection.decisions import (
    DecisionRecord,
    EvidenceRecord,
    SiteDecisionSummary,
    aggregate_site_selection_decisions,
    decision_records_from_selection_result,
    evidence_records_from_site_selection_evidence,
    write_evidence_records_jsonl,
)
from hydromodpy.spatial.site_selection.domain.observations import (
    ObservationEvidence,
    ObservationSpatialMatch,
)
from hydromodpy.spatial.site_selection.evaluation.criteria import (
    CriteriaComponent,
    evaluate_area_criterion,
    evaluate_flow_station_criterion,
    evaluate_geology_criterion,
    evaluate_influence_criterion,
    evaluate_piezometer_criterion,
    evaluate_station_influence_criterion,
)
from hydromodpy.spatial.site_selection.evaluation.selection import (
    SelectionDecision,
    SelectionResult,
    select_delineated_catchments,
)
from hydromodpy.spatial.site_selection.evaluation.spatial_filters import (
    basin_overlap_fraction,
    is_overlap_allowed,
)
from hydromodpy.spatial.site_selection.evidence.annotations import (
    CatchmentAnnotationResult,
    annotate_site_selection_catchments,
)
from hydromodpy.spatial.site_selection.evidence.context import (
    GeologyEvidence,
    annotate_catchments_with_geology_layers,
    annotate_catchments_with_piezometer_layers,
    write_geology_evidence_geojson,
)
from hydromodpy.spatial.site_selection.evidence.exports import (
    write_site_selection_evidence_outputs,
)
from hydromodpy.spatial.site_selection.evidence.observations import (
    build_observation_evidence,
    build_observation_evidence_from_attributes,
)
from hydromodpy.spatial.site_selection.evidence.refs import (
    geology_evidence_ref,
    influence_evidence_ref,
    observation_evidence_ref,
)
from hydromodpy.spatial.site_selection.hydrology.delineation import (
    DelineatedCatchment,
    delineate_candidate_outlet,
    try_delineate_candidate_outlet,
)
from hydromodpy.spatial.site_selection.hydrology.flow_products import (
    SiteSelectionFlowProducts,
    build_site_selection_flow_products,
)
from hydromodpy.spatial.site_selection.hydrology.pipeline import (
    delineate_site_selection_candidates,
)
from hydromodpy.spatial.site_selection.outputs.manifest import (
    SITE_SELECTION_MANIFEST_NAME,
    build_selection_manifest,
    load_selection_manifest,
    validate_selection_manifest,
    write_selection_manifest,
)
from hydromodpy.spatial.site_selection.outputs.pipeline import (
    write_core_site_selection_outputs,
)
from hydromodpy.spatial.site_selection.outputs.writer import (
    SELECTED_SITES_FIELDS,
    SELECTED_SITES_SCHEMA,
    site_record_from_catchment,
    write_basins_geojson,
    write_decision_records_jsonl,
    write_observation_points_geojson,
    write_outlets_geojson,
    write_regional_lab_sites_csv,
    write_selected_sites_csv,
    write_selection_result,
    write_site_decision_summary_csv,
)
from hydromodpy.spatial.site_selection.pipelines.build import (
    SiteSelectionBuildResult,
    build_site_selection_from_dem_area_light,
    build_site_selection_from_generated_network,
    build_site_selection_from_point_records,
)
from hydromodpy.spatial.site_selection.reports.figures import render_site_selection_map
from hydromodpy.spatial.site_selection.reports.html import render_site_selection_html_report
from hydromodpy.spatial.site_selection.reports.plan import render_site_selection_plan_html_report

__all__ = [
    "CandidateOutlet",
    "CandidateGenerationEvidence",
    "CriteriaComponent",
    "CatchmentAnnotationResult",
    "DecisionRecord",
    "DelineatedCatchment",
    "EvidenceRecord",
    "GeologyEvidence",
    "GeneratedCandidateResult",
    "ObservationEvidence",
    "ObservationSpatialMatch",
    "SelectionDecision",
    "SelectionResult",
    "SiteDecisionSummary",
    "SiteSelectionConfig",
    "SiteSelectionFlowProducts",
    "SiteSelectionBuildResult",
    "SITE_SELECTION_MANIFEST_NAME",
    "SELECTED_SITES_FIELDS",
    "SELECTED_SITES_SCHEMA",
    "annotate_catchments_with_geology_layers",
    "annotate_catchments_with_piezometer_layers",
    "annotate_site_selection_catchments",
    "aggregate_site_selection_decisions",
    "build_observation_evidence",
    "build_observation_evidence_from_attributes",
    "build_selection_manifest",
    "build_dem_area_light_candidates",
    "build_generated_network_candidates",
    "build_site_selection_from_dem_area_light",
    "build_site_selection_from_generated_network",
    "build_site_selection_from_point_records",
    "build_site_selection_flow_products",
    "build_station_candidate_outlets",
    "basin_overlap_fraction",
    "candidate_outlets_from_point_records",
    "candidate_outlets_from_rows",
    "candidate_generation_evidence_with_candidate_attributes",
    "delineate_candidate_outlet",
    "delineate_site_selection_candidates",
    "decision_records_from_selection_result",
    "evidence_records_from_site_selection_evidence",
    "evaluate_area_criterion",
    "evaluate_flow_station_criterion",
    "evaluate_geology_criterion",
    "evaluate_influence_criterion",
    "evaluate_piezometer_criterion",
    "evaluate_station_influence_criterion",
    "generate_network_candidate_outlets",
    "geology_evidence_ref",
    "influence_evidence_ref",
    "is_overlap_allowed",
    "load_selection_manifest",
    "observation_evidence_ref",
    "render_site_selection_html_report",
    "render_site_selection_plan_html_report",
    "render_site_selection_map",
    "select_delineated_catchments",
    "site_record_from_catchment",
    "site_selection_search_geometry",
    "thin_candidate_outlets",
    "try_delineate_candidate_outlet",
    "validate_selection_manifest",
    "write_basins_geojson",
    "write_core_site_selection_outputs",
    "write_decision_records_jsonl",
    "write_evidence_records_jsonl",
    "write_geology_evidence_geojson",
    "write_generated_network_geojson",
    "write_observation_points_geojson",
    "write_outlets_geojson",
    "write_regional_lab_sites_csv",
    "write_selected_sites_csv",
    "write_site_selection_evidence_outputs",
    "write_site_decision_summary_csv",
    "write_selection_result",
    "write_selection_manifest",
]
