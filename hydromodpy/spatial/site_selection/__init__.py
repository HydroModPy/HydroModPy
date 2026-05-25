"""Regional basin-site selection helpers."""

from __future__ import annotations

from hydromodpy.spatial.site_selection.build import (
    SiteSelectionBuildResult,
    build_site_selection_from_generated_network,
    build_site_selection_from_point_records,
)
from hydromodpy.spatial.site_selection.candidate_generation import (
    CandidateGenerationEvidence,
    candidate_generation_evidence_with_candidate_attributes,
    generate_network_candidate_outlets,
    write_generated_network_geojson,
)
from hydromodpy.spatial.site_selection.candidate_outlets import (
    CandidateOutlet,
    candidate_outlets_from_point_records,
    candidate_outlets_from_rows,
    thin_candidate_outlets,
)
from hydromodpy.spatial.site_selection.config import SiteSelectionConfig
from hydromodpy.spatial.site_selection.context_evidence import (
    GeologyEvidence,
    annotate_catchments_with_geology_layers,
    annotate_catchments_with_piezometer_layers,
    write_geology_evidence_geojson,
)
from hydromodpy.spatial.site_selection.criteria import (
    CriteriaComponent,
    evaluate_area_criterion,
    evaluate_flow_station_criterion,
    evaluate_geology_criterion,
    evaluate_influence_criterion,
    evaluate_piezometer_criterion,
)
from hydromodpy.spatial.site_selection.delineation import (
    DelineatedCatchment,
    delineate_candidate_outlet,
    try_delineate_candidate_outlet,
)
from hydromodpy.spatial.site_selection.exports import (
    SELECTED_SITES_FIELDS,
    SELECTED_SITES_SCHEMA,
    site_record_from_catchment,
    write_basins_geojson,
    write_observation_points_geojson,
    write_outlets_geojson,
    write_regional_lab_sites_csv,
    write_selected_sites_csv,
    write_selection_result,
)
from hydromodpy.spatial.site_selection.figures import render_site_selection_map
from hydromodpy.spatial.site_selection.filters import (
    basin_overlap_fraction,
    is_overlap_allowed,
)
from hydromodpy.spatial.site_selection.flow_products_adapter import (
    SiteSelectionFlowProducts,
    build_site_selection_flow_products,
)
from hydromodpy.spatial.site_selection.html_report import render_site_selection_html_report
from hydromodpy.spatial.site_selection.manifest import (
    SITE_SELECTION_MANIFEST_NAME,
    build_selection_manifest,
    load_selection_manifest,
    validate_selection_manifest,
    write_selection_manifest,
)
from hydromodpy.spatial.site_selection.observations import (
    build_observation_evidence,
    build_observation_evidence_from_attributes,
)
from hydromodpy.spatial.site_selection.plan_report import render_site_selection_plan_html_report
from hydromodpy.spatial.site_selection.reporting import main as render_selection_report
from hydromodpy.spatial.site_selection.selection import (
    SelectionDecision,
    SelectionResult,
    select_delineated_catchments,
)
from hydromodpy.spatial.site_selection.types import ObservationEvidence, ObservationSpatialMatch

__all__ = [
    "CandidateOutlet",
    "CandidateGenerationEvidence",
    "CriteriaComponent",
    "DelineatedCatchment",
    "GeologyEvidence",
    "ObservationEvidence",
    "ObservationSpatialMatch",
    "SelectionDecision",
    "SelectionResult",
    "SiteSelectionConfig",
    "SiteSelectionFlowProducts",
    "SiteSelectionBuildResult",
    "SITE_SELECTION_MANIFEST_NAME",
    "SELECTED_SITES_FIELDS",
    "SELECTED_SITES_SCHEMA",
    "annotate_catchments_with_geology_layers",
    "annotate_catchments_with_piezometer_layers",
    "build_observation_evidence",
    "build_observation_evidence_from_attributes",
    "build_selection_manifest",
    "build_site_selection_from_generated_network",
    "build_site_selection_from_point_records",
    "build_site_selection_flow_products",
    "basin_overlap_fraction",
    "candidate_outlets_from_point_records",
    "candidate_outlets_from_rows",
    "candidate_generation_evidence_with_candidate_attributes",
    "delineate_candidate_outlet",
    "evaluate_area_criterion",
    "evaluate_flow_station_criterion",
    "evaluate_geology_criterion",
    "evaluate_influence_criterion",
    "evaluate_piezometer_criterion",
    "generate_network_candidate_outlets",
    "is_overlap_allowed",
    "load_selection_manifest",
    "render_site_selection_html_report",
    "render_selection_report",
    "render_site_selection_plan_html_report",
    "render_site_selection_map",
    "select_delineated_catchments",
    "site_record_from_catchment",
    "thin_candidate_outlets",
    "try_delineate_candidate_outlet",
    "validate_selection_manifest",
    "write_basins_geojson",
    "write_geology_evidence_geojson",
    "write_generated_network_geojson",
    "write_observation_points_geojson",
    "write_outlets_geojson",
    "write_regional_lab_sites_csv",
    "write_selected_sites_csv",
    "write_selection_result",
    "write_selection_manifest",
]
