"""Public export facade for site-selection results."""

from __future__ import annotations

from pathlib import Path

from hydromodpy.spatial.site_selection.decisions import (
    aggregate_site_selection_decisions,
    decision_records_from_selection_result,
    write_decision_records_jsonl,
    write_site_decision_summary_csv,
)
from hydromodpy.spatial.site_selection.evaluation.selection import SelectionResult
from hydromodpy.spatial.site_selection.outputs.geojson import (
    write_basins_geojson,
    write_observation_points_geojson,
    write_outlets_geojson,
)
from hydromodpy.spatial.site_selection.outputs.geospatial import (
    GPKG_NAME,
    write_observation_points_geopackage,
    write_observation_points_geoparquet,
    write_selection_geopackage,
    write_selection_geoparquet_layers,
)
from hydromodpy.spatial.site_selection.outputs.schemas import (
    REGIONAL_LAB_SITES_FIELDS,
    SELECTED_SITES_FIELDS,
    SELECTED_SITES_SCHEMA,
    site_record_from_catchment,
)
from hydromodpy.spatial.site_selection.outputs.tabular import (
    write_criteria_components_jsonl,
    write_csv,
    write_jsonl,
    write_regional_lab_sites_csv,
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
    write_regional_lab_csv_output: bool = True,
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
    if write_regional_lab_csv_output:
        paths["regional_lab_sites_csv"] = write_regional_lab_sites_csv(
            root / "regional_lab_sites.csv",
            result.selected,
            selection_id=selection_id,
            region_id=region_id,
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
    "REGIONAL_LAB_SITES_FIELDS",
    "SELECTED_SITES_FIELDS",
    "SELECTED_SITES_SCHEMA",
    "site_record_from_catchment",
    "write_basins_geojson",
    "write_criteria_components_jsonl",
    "write_csv",
    "write_jsonl",
    "write_observation_points_geojson",
    "write_observation_points_geopackage",
    "write_observation_points_geoparquet",
    "write_selection_geopackage",
    "write_selection_geoparquet_layers",
    "write_outlets_geojson",
    "write_decision_records_jsonl",
    "write_regional_lab_sites_csv",
    "write_selected_sites_csv",
    "write_site_decision_summary_csv",
    "write_selection_result",
]
