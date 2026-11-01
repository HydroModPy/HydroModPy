"""Public export facade for site-selection results.

Core output phase for site-selection builds.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from hydromodpy.site_selection.config.site_selection_config import SiteSelectionConfig
from hydromodpy.site_selection.decisions.aggregate import aggregate_site_selection_decisions
from hydromodpy.site_selection.decisions.records import (
    decision_records_from_selection_result,
)
from hydromodpy.site_selection.domain.observation_evidence import ObservationEvidence
from hydromodpy.site_selection.evaluation.selection import SelectionResult
from hydromodpy.site_selection.evidence.geology_layers import GeologyEvidence
from hydromodpy.site_selection.evidence.influence import InfluenceEvidence
from hydromodpy.site_selection.outputs.decision_files import (
    write_decision_records_jsonl,
    write_site_decision_summary_csv,
)
from hydromodpy.site_selection.outputs.evidence_files import (
    write_site_selection_evidence_outputs,
)
from hydromodpy.site_selection.outputs.geojson import (
    write_basins_geojson,
    write_observation_points_geojson,
    write_outlets_geojson,
)
from hydromodpy.site_selection.outputs.geospatial import (
    GPKG_NAME,
    write_selection_geopackage,
    write_selection_geoparquet_layers,
)
from hydromodpy.site_selection.outputs.schemas import (
    SELECTED_SITES_FIELDS,
    SELECTED_SITES_SCHEMA,
    site_record_from_catchment,
)
from hydromodpy.site_selection.outputs.tabular import (
    write_criteria_components_jsonl,
    write_csv,
    write_jsonl,
    write_selected_sites_csv,
)


def write_selection_result(
    output_root: str | Path,
    result: SelectionResult,
    *,
    selection_id: str,
    region_id: str = "",
    write_selected: bool = True,
    write_rejected: bool = True,
    write_geojson: bool = True,
    write_geoparquet: bool = False,
    write_geopackage: bool = False,
) -> dict[str, Path]:
    """Write the core outputs for one selection result."""

    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    if write_selected:
        paths["selected_sites_csv"] = write_selected_sites_csv(
            root / "selected_sites.csv",
            result.selected,
            selection_id=selection_id,
            region_id=region_id,
        )
    if write_rejected:
        paths["rejected_sites_csv"] = write_csv(
            root / "rejected_sites.csv",
            [catchment.to_record() for catchment in result.rejected],
        )
    if write_geojson:
        paths["selected_outlets_geojson"] = write_outlets_geojson(
            root / "selected_outlets.geojson",
            result.selected,
            selection_id=selection_id,
            region_id=region_id,
            site_status="selected",
        )
        paths["rejected_outlets_geojson"] = write_outlets_geojson(
            root / "rejected_outlets.geojson",
            result.rejected,
            selection_id=selection_id,
            region_id=region_id,
            site_status="rejected",
        )
        paths["selected_basins_geojson"] = write_basins_geojson(
            root / "selected_basins.geojson",
            result.selected,
            selection_id=selection_id,
            region_id=region_id,
            site_status="selected",
        )
        paths["rejected_basins_geojson"] = write_basins_geojson(
            root / "rejected_basins.geojson",
            result.rejected,
            selection_id=selection_id,
            region_id=region_id,
            site_status="rejected",
        )
    if write_geopackage:
        gpkg_path = write_selection_geopackage(
            root / GPKG_NAME,
            selected=result.selected,
            rejected=result.rejected,
            selection_id=selection_id,
            region_id=region_id,
        )
        if gpkg_path is not None:
            paths["site_selection_gpkg"] = gpkg_path
    if write_geoparquet:
        paths.update(
            write_selection_geoparquet_layers(
                root,
                selected=result.selected,
                rejected=result.rejected,
                selection_id=selection_id,
                region_id=region_id,
            )
        )
    paths["criteria_components_jsonl"] = write_criteria_components_jsonl(
        root / "criteria_components.jsonl",
        result.criteria_components,
    )
    decision_records = decision_records_from_selection_result(result, run_id=selection_id)
    decision_summaries = aggregate_site_selection_decisions(decision_records)
    paths["site_selection_decisions_csv"] = write_site_decision_summary_csv(
        root / "site_selection_decisions.csv",
        decision_summaries,
    )
    paths["site_selection_decisions_jsonl"] = write_decision_records_jsonl(
        root / "site_selection_decisions.jsonl",
        decision_records,
    )
    return paths


__all__ = [
    "GPKG_NAME",
    "SELECTED_SITES_FIELDS",
    "SELECTED_SITES_SCHEMA",
    "site_record_from_catchment",
    "write_basins_geojson",
    "write_criteria_components_jsonl",
    "write_csv",
    "write_jsonl",
    "write_observation_points_geojson",
    "write_selection_geopackage",
    "write_selection_geoparquet_layers",
    "write_outlets_geojson",
    "write_decision_records_jsonl",
    "write_selected_sites_csv",
    "write_site_decision_summary_csv",
    "write_selection_result",
    "write_core_site_selection_outputs",
]


def write_core_site_selection_outputs(
    root: str | Path,
    *,
    config: SiteSelectionConfig,
    selection: SelectionResult,
    region_id: str = "",
    observation_evidence: Iterable[ObservationEvidence] = (),
    piezometer_evidence: Iterable[ObservationEvidence] = (),
    influence_evidence: Iterable[InfluenceEvidence] = (),
    geology_evidence: Iterable[GeologyEvidence] = (),
    write_observation_vectors: bool = True,
    write_context_vectors: bool = True,
) -> dict[str, Path]:
    """Write core selection outputs and all evidence outputs."""

    output_paths = write_selection_result(
        root,
        selection,
        selection_id=config.selection_id,
        region_id=region_id,
        write_selected=config.output.write_csv and config.output.write_selected,
        write_rejected=config.output.write_csv and config.output.write_rejected,
        write_geojson=config.output.write_geojson,
        write_geoparquet=config.output.write_geoparquet,
        write_geopackage=config.output.write_geopackage,
    )
    return write_site_selection_evidence_outputs(
        root,
        selection_id=config.selection_id,
        output=config.output,
        output_paths=output_paths,
        observation_evidence=observation_evidence,
        piezometer_evidence=piezometer_evidence,
        influence_evidence=influence_evidence,
        geology_evidence=geology_evidence,
        write_observation_vectors=write_observation_vectors,
        write_context_vectors=write_context_vectors,
    )
