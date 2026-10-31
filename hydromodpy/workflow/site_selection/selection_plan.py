"""The plan of a site selection, checked before any heavy spatial computation."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.spatial.site_selection.config.site_selection_config import SiteSelectionConfig
from hydromodpy.spatial.site_selection.outputs.manifest import path_or_none
from hydromodpy.workflow.site_selection.data_loading import load_site_selection_config

__all__ = [
    "PLAN_MANIFEST_NAME",
    "ReportRenderer",
    "SiteSelectionPlan",
    "plan_site_selection",
]


PLAN_MANIFEST_NAME = "site_selection_plan.json"
ProgressCallback = Callable[[str], None]
ReportRenderer = Callable[[str | Path], Path]
"""Draws the HTML report of a manifest and returns the page it wrote."""


@dataclass(frozen=True)
class SiteSelectionPlan:
    """Validated plan produced before any heavy spatial computation."""

    config: SiteSelectionConfig
    manifest: dict[str, Any]

    def write_manifest(self, path: str | Path | None = None) -> Path:
        """Write the plan manifest as JSON."""

        destination = (
            Path(path) if path is not None else self.config.output_root / PLAN_MANIFEST_NAME
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(self.manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return destination


def plan_site_selection(path: str | Path) -> SiteSelectionPlan:
    """Validate a site-selection config and return a reproducible plan summary."""

    cfg = load_site_selection_config(path)
    manifest = {
        "selection_id": cfg.selection_id,
        "output_root": str(cfg.output_root),
        "strategy": {
            "principle": cfg.strategy.principle,
            "profile": cfg.strategy.profile,
            "effective_profile": cfg.effective_profile,
            "primary_axes": list(cfg.strategy.primary_axes),
            "primary_observation_type": cfg.strategy.primary_observation_type,
            "candidate_mode": cfg.outlets.candidate_mode,
        },
        "territory": {
            "mode": cfg.territory.mode,
            "country": cfg.territory.country,
            "regions": list(cfg.territory.regions),
            "departments": list(cfg.territory.departments),
            "bbox": cfg.territory.bbox,
            "polygon_file": path_or_none(cfg.territory.polygon_file),
        },
        "dem": {
            "source": cfg.dem.source,
            "path": path_or_none(cfg.dem.path),
            "margin_km": cfg.dem.margin_km,
            "request_extent": cfg.dem.request_extent,
            "map_background_extent": cfg.dem.map_background_extent,
            "force_refresh": cfg.dem.force_refresh,
        },
        "input": {
            "mode": cfg.input.mode,
            "catchments_csv": path_or_none(cfg.input.catchments_csv),
            "region_id": cfg.input.region_id,
            "workspace_root": path_or_none(cfg.input.workspace_root),
            "data_root": path_or_none(cfg.input.data_root),
            "write_plan_manifest": cfg.input.write_plan_manifest,
            "delineate_from_outlets": cfg.input.delineate_from_outlets,
        },
        "hydrology": {
            "method": cfg.hydrology.method,
            "flow_algorithm": cfg.hydrology.flow_algorithm,
            "dem_correction_type": cfg.hydrology.dem_correction_type,
            "network_threshold_area_km2": cfg.hydrology.network_threshold_area_km2,
            "compute_strahler": cfg.hydrology.compute_strahler,
        },
        "outlets": {
            "candidate_mode": cfg.outlets.candidate_mode,
            "snap_strategy": cfg.outlets.snap_strategy,
            "snap_dist_m": cfg.outlets.snap_dist_m,
            "max_generated_candidates": cfg.outlets.max_generated_candidates,
            "max_rejected_candidate_audit_records": (
                cfg.outlets.max_rejected_candidate_audit_records
            ),
            "max_generated_network_cells": cfg.outlets.max_generated_network_cells,
            "reference_network_source": cfg.outlets.reference_network_source,
            "reference_network_path": path_or_none(cfg.outlets.reference_network_path),
            "reference_network_max_distance_m": cfg.outlets.reference_network_max_distance_m,
            "reference_network_fetch_margin_m": cfg.outlets.reference_network_fetch_margin_m,
        },
        "criteria": {
            "area_mode": cfg.criteria.area.mode,
            "geology_mode": cfg.criteria.geology.mode,
            "flow_station_mode": cfg.criteria.observations.flow_station.mode,
            "piezometer_mode": cfg.criteria.observations.piezometer_mode,
            "influence_layers": [
                layer.model_dump(mode="json") for layer in cfg.criteria.influence.layers
            ],
            "geology_layers": [
                layer.model_dump(mode="json") for layer in cfg.criteria.geology.layers
            ],
            "piezometer_layers": [
                layer.model_dump(mode="json")
                for layer in cfg.criteria.observations.piezometer_layers
            ],
            "area_ranges": [
                area_range.model_dump(mode="json") for area_range in cfg.criteria.area.ranges
            ],
        },
        "map_context": {
            "layers": [
                {
                    "name": layer.name,
                    "path": path_or_none(layer.path),
                    "role": layer.role,
                    "label_field": layer.label_field,
                }
                for layer in cfg.map_context.layers
            ],
        },
        "planned_outputs": _planned_outputs(cfg),
    }
    return SiteSelectionPlan(config=cfg, manifest=manifest)


def format_project_extent(
    extent: tuple[float, float, float, float] | None,
) -> str:
    if extent is None:
        return "none"
    xmin, ymin, xmax, ymax = extent
    return f"({xmin:.1f}, {ymin:.1f}, {xmax:.1f}, {ymax:.1f})"


def _planned_outputs(cfg: SiteSelectionConfig) -> list[str]:
    outputs: list[str] = []
    if cfg.output.write_rejected:
        outputs.append("rejected")
    if cfg.output.write_selected:
        outputs.append("selected")
    if cfg.output.write_geojson:
        outputs.append("geojson")
    if cfg.output.write_geoparquet:
        outputs.append("geoparquet")
    if cfg.output.write_geopackage:
        outputs.append("geopackage")
    if cfg.output.write_csv:
        outputs.append("csv")
    if cfg.output.write_report_html:
        outputs.append("report_html")
    return outputs
