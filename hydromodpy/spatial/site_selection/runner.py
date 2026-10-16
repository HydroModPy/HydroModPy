"""Run a site selection declared in a TOML file.

``hmp site select <file>`` calls :func:`run_site_selection`. The file holds a
``[site_selection]`` section, plus ``[hydrometry]`` for an observation-led
selection and ``[data.dem]`` to name the DEM. Every output goes under the
``output_root`` the file declares. The HTML report is drawn by the reporting
layer: the caller passes its renderers, this module never imports them.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from hydromodpy.core.exceptions import (
    ConfigError,
    ConfigMissingError,
)
from hydromodpy.core.logging import get_logger
from hydromodpy.core.toml_io.loader import load_toml_with_base_config
from hydromodpy.data.variables.dem.config import DemConfig as DataDemConfig
from hydromodpy.data.variables.hydrometry.config import HydrometryConfig
from hydromodpy.spatial.site_selection._runner_csv import (
    _float_from_row,
    _optional_float,
    _required_text,
)
from hydromodpy.spatial.site_selection._runner_dem import (
    _candidate_outlets_for_dem_request,
    _load_data_dem_config,
    _maybe_delineate_from_outlets,
    _maybe_resolve_map_dem_for_review,
    _observation_request_bbox_wgs84,
    _observed_dem_request_bbox,
    _resolve_dem_path_for_generated_selection,
    _resolve_dem_path_for_observed_selection,
)
from hydromodpy.spatial.site_selection._runner_paths import (
    _data_access_error,
    _path_or_none,
    _resolve_csv_path,
    _resolve_optional_path,
    _resolve_paths,
    _with_default_data_root,
)
from hydromodpy.spatial.site_selection.candidates.outlets import (
    CandidateOutlet,
)
from hydromodpy.spatial.site_selection.config import SiteSelectionConfig
from hydromodpy.spatial.site_selection.evaluation.selection import (
    SelectionResult,
    select_delineated_catchments,
)
from hydromodpy.spatial.site_selection.evidence.annotations import (
    annotate_site_selection_catchments,
)
from hydromodpy.spatial.site_selection.evidence.observations import (
    build_observation_evidence_from_attributes,
)
from hydromodpy.spatial.site_selection.hydrology.delineation import (
    DelineatedCatchment,
)
from hydromodpy.spatial.site_selection.hydrology.flow_products import (
    FlowProductsBuilder,
)
from hydromodpy.spatial.site_selection.outputs.artifacts import write_manifest_and_optional_report
from hydromodpy.spatial.site_selection.outputs.cleanup import (
    cleanup_site_selection_intermediate_rasters,
)
from hydromodpy.spatial.site_selection.outputs.pipeline import (
    write_core_site_selection_outputs,
)
from hydromodpy.spatial.site_selection.pipelines.build import (
    SiteSelectionBuildResult,
    build_site_selection_from_dem_area_light,
    build_site_selection_from_generated_network,
    build_site_selection_from_point_records,
)
from hydromodpy.spatial.site_selection.runner_data import (
    DemLoader,
    HydrometryLoader,
    load_hydrometry_records,
)

logger = get_logger(__name__)

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


def load_site_selection_config(path: str | Path) -> SiteSelectionConfig:
    """Load and validate the ``[site_selection]`` section of a TOML file."""

    config_path = Path(path).expanduser().resolve()
    raw = load_toml_with_base_config(config_path)
    section = raw.get("site_selection")
    if not isinstance(section, dict):
        raise ConfigMissingError("TOML file must contain a [site_selection] section.")
    cfg = SiteSelectionConfig.model_validate(section)
    return _resolve_paths(cfg, base_dir=config_path.parent)


def load_hydrometry_config_for_site_selection(path: str | Path) -> HydrometryConfig:
    """Load a companion ``[hydrometry]`` section for observation-led selection."""

    config_path = Path(path).expanduser().resolve()
    raw = load_toml_with_base_config(config_path)
    section = raw.get("hydrometry")
    if not isinstance(section, dict):
        raise ConfigMissingError("TOML file must contain a [hydrometry] section.")
    cfg = HydrometryConfig.model_validate(section)
    sources = []
    for source in cfg.sources:
        source_path = getattr(source, "path", None)
        if source_path is not None:
            source = source.model_copy(
                update={"path": _resolve_optional_path(source_path, base_dir=config_path.parent)}
            )
        sources.append(source)
    return cfg.model_copy(update={"sources": sources})


def load_data_dem_config_for_site_selection(path: str | Path) -> DataDemConfig | None:
    """Load an optional ``[data.dem]`` section for site-selection DEM resolution."""

    return _load_data_dem_config(path)


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
            "polygon_file": _path_or_none(cfg.territory.polygon_file),
        },
        "dem": {
            "source": cfg.dem.source,
            "path": _path_or_none(cfg.dem.path),
            "margin_km": cfg.dem.margin_km,
            "request_extent": cfg.dem.request_extent,
            "map_background_extent": cfg.dem.map_background_extent,
            "force_refresh": cfg.dem.force_refresh,
        },
        "input": {
            "mode": cfg.input.mode,
            "catchments_csv": _path_or_none(cfg.input.catchments_csv),
            "region_id": cfg.input.region_id,
            "workspace_root": _path_or_none(cfg.input.workspace_root),
            "data_root": _path_or_none(cfg.input.data_root),
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
            "reference_network_path": _path_or_none(cfg.outlets.reference_network_path),
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
                    "path": _path_or_none(layer.path),
                    "role": layer.role,
                    "label_field": layer.label_field,
                }
                for layer in cfg.map_context.layers
            ],
        },
        "planned_outputs": _planned_outputs(cfg),
    }
    return SiteSelectionPlan(config=cfg, manifest=manifest)


def load_delineated_catchments_csv(path: str | Path) -> list[DelineatedCatchment]:
    """Load a small delineated-catchment CSV for selection-only workflows."""

    source = Path(path).expanduser().resolve()
    with source.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    catchments: list[DelineatedCatchment] = []
    for index, row in enumerate(rows, start=1):
        site_id = _required_text(row, "site_id", row_number=index)
        x = _float_from_row(row, "x_outlet", fallback_field="x", row_number=index)
        y = _float_from_row(row, "y_outlet", fallback_field="y", row_number=index)
        area_km2 = _optional_float(row.get("area_km2"))
        outlet = CandidateOutlet(
            candidate_id=row.get("candidate_id") or site_id,
            x=x,
            y=y,
            crs=row.get("outlet_crs") or row.get("crs") or "EPSG:2154",
            source=row.get("source") or "delineated_csv",
            source_feature_id=row.get("source_feature_id") or site_id,
            source_label=row.get("site_label") or site_id,
            priority=_optional_float(row.get("priority")) or 0.0,
            attributes={str(key): value for key, value in row.items()},
        )
        catchments.append(
            DelineatedCatchment(
                site_id=site_id,
                outlet=outlet,
                outlet_shp=_resolve_csv_path(row.get("outlet_shp"), base_dir=source.parent),
                outlet_snap_shp=_resolve_csv_path(
                    row.get("outlet_snap_shp"),
                    base_dir=source.parent,
                ),
                watershed_tif=_resolve_csv_path(row.get("watershed_tif"), base_dir=source.parent),
                watershed_shp=_resolve_csv_path(row.get("watershed_shp"), base_dir=source.parent),
                area_km2=area_km2,
                status=row.get("status") or "delineated",
                failure_reason=row.get("failure_reason") or "",
            )
        )
    return catchments


def select_delineated_catchments_from_csv(
    *,
    config_path: str | Path,
    catchments_csv: str | Path,
    output_root: str | Path | None = None,
    region_id: str = "",
    backend: object | None = None,
    flow_products_builder: FlowProductsBuilder | None = None,
    delineation_builder=None,
    area_reader=None,
    dem_loader: DemLoader | None = None,
    report_renderer: ReportRenderer | None = None,
) -> tuple[SelectionResult, dict[str, Path]]:
    """Run the selection stage from a pre-delineated catchments CSV."""

    cfg = load_site_selection_config(config_path)
    catchments = load_delineated_catchments_csv(catchments_csv)
    target_root = Path(output_root).expanduser().resolve() if output_root else cfg.output_root
    cfg_for_outputs = _with_default_data_root(cfg.model_copy(update={"output_root": target_root}))
    catchments, flow_manifest = _maybe_delineate_from_outlets(
        catchments=catchments,
        config=cfg_for_outputs,
        config_path=Path(config_path).expanduser().resolve(),
        backend=backend,
        flow_products_builder=flow_products_builder,
        delineation_builder=delineation_builder,
        area_reader=area_reader,
        dem_loader=dem_loader,
    )
    if not flow_manifest:
        flow_manifest = _maybe_resolve_map_dem_for_review(
            config=cfg_for_outputs,
            catchments=catchments,
            config_path=Path(config_path).expanduser().resolve(),
            dem_loader=dem_loader,
        )
    annotations = annotate_site_selection_catchments(
        catchments,
        criteria=cfg.criteria,
    )
    catchments = annotations.catchments
    result = select_delineated_catchments(
        catchments,
        criteria=cfg.criteria,
        spatial_selection=cfg.spatial_selection,
        selection_principle=cfg.strategy.principle,
    )
    observation_evidence = [
        evidence
        for catchment in catchments
        for evidence in build_observation_evidence_from_attributes(
            site_id=catchment.site_id,
            attributes=catchment.outlet.attributes,
        )
    ]
    observation_evidence.extend(annotations.piezometer_evidence)
    paths = write_core_site_selection_outputs(
        target_root,
        config=cfg,
        selection=result,
        region_id=region_id,
        observation_evidence=observation_evidence,
        piezometer_evidence=annotations.piezometer_evidence,
        influence_evidence=annotations.influence_evidence,
        geology_evidence=annotations.geology_evidence,
    )
    paths.update(
        write_manifest_and_optional_report(
            config=cfg_for_outputs,
            selection=result,
            output_paths=paths,
            action="delineated_catchments",
            input_paths={"catchments_csv": catchments_csv},
            flow_products=flow_manifest,
            report_renderer=report_renderer,
        )
    )
    if not cfg_for_outputs.output.keep_intermediate_rasters:
        cleanup_site_selection_intermediate_rasters(
            output_root=target_root,
            catchments=catchments,
        )
    return result, paths


def _emit_progress(callback: ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def _log_progress(message: str) -> None:
    logger.debug("[site_selection] %s", message)


def _format_project_extent(
    extent: tuple[float, float, float, float] | None,
) -> str:
    if extent is None:
        return "none"
    xmin, ymin, xmax, ymax = extent
    return f"({xmin:.1f}, {ymin:.1f}, {xmax:.1f}, {ymax:.1f})"


def build_site_selection_from_hydrometry_config(
    *,
    config: SiteSelectionConfig,
    hydrometry_config: HydrometryConfig,
    workspace_root: str | Path | None = None,
    data_root: str | Path | None = None,
    project_extent: tuple | None = None,
    project_period: tuple[datetime, datetime] | None = None,
    hydrometry_loader: HydrometryLoader | None = None,
    **build_kwargs: Any,
) -> SiteSelectionBuildResult:
    """Load hydrometry through data managers, then run spatial site selection."""

    try:
        records = load_hydrometry_records(
            hydrometry_config,
            workspace_root=workspace_root,
            data_root=data_root,
            project_extent=project_extent,
            project_period=project_period,
            loader=hydrometry_loader,
        )
    except Exception as exc:
        raise ConfigError(
            _data_access_error("hydrometry", data_root=data_root, detail=exc)
        ) from exc
    return build_site_selection_from_point_records(
        config=config,
        point_records=records,
        **build_kwargs,
    )


def build_observed_site_selection_from_toml(
    *,
    config_path: str | Path,
    output_root: str | Path | None = None,
    workspace_root: str | Path | None = None,
    data_root: str | Path | None = None,
    project_extent: tuple | None = None,
    hydrometry_loader: HydrometryLoader | None = None,
    dem_loader: DemLoader | None = None,
    backend: object | None = None,
    flow_products_builder: FlowProductsBuilder | None = None,
    delineation_builder=None,
    area_reader=None,
    write_outputs: bool = True,
    progress_callback: ProgressCallback | None = None,
    report_renderer: ReportRenderer | None = None,
) -> SiteSelectionBuildResult:
    """Build an observation-led selection from ``[site_selection]`` + ``[hydrometry]``."""

    path = Path(config_path).expanduser().resolve()
    cfg = load_site_selection_config(path)
    target_root = Path(output_root).expanduser().resolve() if output_root else cfg.output_root
    cfg = _with_default_data_root(
        cfg.model_copy(update={"output_root": target_root}),
        data_root,
    )
    hydrometry_cfg = load_hydrometry_config_for_site_selection(path)
    observation_extent = project_extent or _observation_request_bbox_wgs84(cfg)
    _emit_progress(
        progress_callback,
        (
            f"{cfg.selection_id}: loading hydrometry records "
            f"for extent {_format_project_extent(observation_extent)}"
        ),
    )
    try:
        records = load_hydrometry_records(
            hydrometry_cfg,
            workspace_root=workspace_root or cfg.input.workspace_root,
            data_root=cfg.input.data_root,
            project_extent=observation_extent,
            loader=hydrometry_loader,
        )
    except Exception as exc:
        raise ConfigError(
            _data_access_error("hydrometry", data_root=cfg.input.data_root, detail=exc)
        ) from exc
    _emit_progress(progress_callback, f"{cfg.selection_id}: loaded {len(records)} records")
    candidate_outlets = _candidate_outlets_for_dem_request(cfg, records)
    dem_extent = _observed_dem_request_bbox(
        config=cfg,
        candidate_outlets=candidate_outlets,
    )
    if candidate_outlets:
        _emit_progress(
            progress_callback,
            (
                f"{cfg.selection_id}: DEM extent from {len(candidate_outlets)} "
                f"station outlets {_format_project_extent(dem_extent)}"
            ),
        )
    elif cfg.dem.request_extent == "outlets":
        _emit_progress(
            progress_callback,
            (
                f"{cfg.selection_id}: DEM extent falls back to territory "
                "because no station outlet was available"
            ),
        )
    _emit_progress(progress_callback, f"{cfg.selection_id}: resolving calculation DEM")
    dem_path = _resolve_dem_path_for_observed_selection(
        config=cfg,
        config_path=path,
        workspace_root=workspace_root or cfg.input.workspace_root,
        data_root=cfg.input.data_root,
        dem_loader=dem_loader,
        candidate_outlets=candidate_outlets,
    )
    _emit_progress(progress_callback, f"{cfg.selection_id}: calculation DEM ready: {dem_path}")
    _emit_progress(
        progress_callback,
        f"{cfg.selection_id}: building flow products, catchments and report artifacts",
    )
    result = build_site_selection_from_point_records(
        config=cfg,
        point_records=records,
        dem_init_path=dem_path,
        backend=backend,
        flow_products_builder=flow_products_builder,
        delineation_builder=delineation_builder,
        area_reader=area_reader,
        write_outputs=write_outputs,
        report_renderer=report_renderer,
    )
    _emit_progress(
        progress_callback,
        (
            f"{cfg.selection_id}: finished with {len(result.candidates)} candidates, "
            f"{len(result.selection.selected)} selected, "
            f"{len(result.selection.rejected)} rejected"
        ),
    )
    return result


def build_generated_site_selection_from_toml(
    *,
    config_path: str | Path,
    output_root: str | Path | None = None,
    workspace_root: str | Path | None = None,
    data_root: str | Path | None = None,
    dem_loader: DemLoader | None = None,
    backend: object | None = None,
    flow_products_builder: FlowProductsBuilder | None = None,
    delineation_builder=None,
    area_reader=None,
    write_outputs: bool = True,
    progress_callback: ProgressCallback | None = None,
    report_renderer: ReportRenderer | None = None,
) -> SiteSelectionBuildResult:
    """Build a site selection from DEM/network-generated candidates."""

    path = Path(config_path).expanduser().resolve()
    cfg = load_site_selection_config(path)
    target_root = Path(output_root).expanduser().resolve() if output_root else cfg.output_root
    cfg = _with_default_data_root(
        cfg.model_copy(update={"output_root": target_root}),
        data_root,
    )
    _emit_progress(progress_callback, f"{cfg.selection_id}: resolving calculation DEM")
    dem_path = _resolve_dem_path_for_generated_selection(
        config=cfg,
        config_path=path,
        workspace_root=workspace_root or cfg.input.workspace_root,
        data_root=cfg.input.data_root,
        dem_loader=dem_loader,
    )
    _emit_progress(progress_callback, f"{cfg.selection_id}: calculation DEM ready: {dem_path}")
    _emit_progress(
        progress_callback,
        f"{cfg.selection_id}: generating candidates, catchments and report artifacts",
    )
    result = build_site_selection_from_generated_network(
        config=cfg,
        dem_init_path=dem_path,
        backend=backend,
        flow_products_builder=flow_products_builder,
        delineation_builder=delineation_builder,
        area_reader=area_reader,
        write_outputs=write_outputs,
        report_renderer=report_renderer,
    )
    _emit_progress(
        progress_callback,
        (
            f"{cfg.selection_id}: finished with {len(result.candidates)} candidates, "
            f"{len(result.selection.selected)} selected, "
            f"{len(result.selection.rejected)} rejected"
        ),
    )
    return result


def build_dem_area_light_site_selection_from_toml(
    *,
    config_path: str | Path,
    output_root: str | Path | None = None,
    workspace_root: str | Path | None = None,
    data_root: str | Path | None = None,
    dem_loader: DemLoader | None = None,
    backend: object | None = None,
    flow_products_builder: FlowProductsBuilder | None = None,
    raw_accumulation_builder=None,
    delineation_builder=None,
    area_reader=None,
    write_outputs: bool = True,
    progress_callback: ProgressCallback | None = None,
    report_renderer: ReportRenderer | None = None,
) -> SiteSelectionBuildResult:
    """Build a DEM-only light area-based site selection."""

    path = Path(config_path).expanduser().resolve()
    cfg = load_site_selection_config(path)
    target_root = Path(output_root).expanduser().resolve() if output_root else cfg.output_root
    cfg = _with_default_data_root(
        cfg.model_copy(update={"output_root": target_root}),
        data_root,
    )
    _emit_progress(progress_callback, f"{cfg.selection_id}: resolving calculation DEM")
    dem_path = _resolve_dem_path_for_generated_selection(
        config=cfg,
        config_path=path,
        workspace_root=workspace_root or cfg.input.workspace_root,
        data_root=cfg.input.data_root,
        dem_loader=dem_loader,
    )
    _emit_progress(progress_callback, f"{cfg.selection_id}: calculation DEM ready: {dem_path}")
    _emit_progress(
        progress_callback,
        f"{cfg.selection_id}: scanning DEM area candidates and building report artifacts",
    )
    result = build_site_selection_from_dem_area_light(
        config=cfg,
        dem_init_path=dem_path,
        backend=backend,
        flow_products_builder=flow_products_builder,
        raw_accumulation_builder=raw_accumulation_builder,
        delineation_builder=delineation_builder,
        area_reader=area_reader,
        write_outputs=write_outputs,
        report_renderer=report_renderer,
    )
    _emit_progress(
        progress_callback,
        (
            f"{cfg.selection_id}: finished with {len(result.candidates)} candidates, "
            f"{len(result.selection.selected)} selected, "
            f"{len(result.selection.rejected)} rejected"
        ),
    )
    return result


@dataclass(frozen=True)
class SelectionRun:
    """What one selection did: its action, its counts and the files it wrote."""

    action: str
    selection_id: str
    output_root: Path
    counts: dict[str, int]
    outputs: dict[str, Path]


def run_site_selection(
    config_path: str | Path,
    *,
    report_renderer: ReportRenderer | None = None,
    plan_report_renderer: ReportRenderer | None = None,
    progress_callback: ProgressCallback | None = None,
) -> SelectionRun:
    """Run the selection a TOML file declares and return what it wrote.

    ``[site_selection.input] mode`` picks the action; ``plan_only`` validates
    the file and writes its plan manifest. :func:`plan_site_selection` alone
    validates without writing anything. The renderers
    draw the HTML report when ``[site_selection.output] write_report_html`` is
    true; without them no report is written.
    """

    path = Path(config_path).expanduser().resolve()
    raw = load_toml_with_base_config(path)
    _refuse_a_workflow_mode(raw)
    cfg = load_site_selection_config(path)
    action = _resolve_action(cfg, raw)
    progress = progress_callback or _log_progress

    if action == "plan":
        return _run_plan(path, cfg, plan_report_renderer=plan_report_renderer)

    if action == "delineated_catchments":
        if cfg.input.catchments_csv is None:
            raise ConfigMissingError("site_selection.input.catchments_csv is required.")
        result, paths = select_delineated_catchments_from_csv(
            config_path=path,
            catchments_csv=cfg.input.catchments_csv,
            region_id=cfg.input.region_id,
            report_renderer=report_renderer,
        )
        return SelectionRun(
            action=action,
            selection_id=cfg.selection_id,
            output_root=cfg.output_root,
            counts={"selected": len(result.selected), "rejected": len(result.rejected)},
            outputs=dict(paths),
        )

    if action == "generated_candidates":
        if cfg.outlets.candidate_mode != "network_sampling":
            raise ConfigError(
                "site_selection.input.mode='generated_candidates' requires "
                "site_selection.outlets.candidate_mode='network_sampling'."
            )
        build = build_generated_site_selection_from_toml
    elif action == "dem_area_light":
        build = build_dem_area_light_site_selection_from_toml
    else:
        if cfg.strategy.principle != "observation_led":
            raise ConfigError(
                "site_selection input mode 'hydrometry' currently requires "
                "strategy.principle='observation_led'."
            )
        build = build_observed_site_selection_from_toml
    built = build(
        config_path=path,
        workspace_root=cfg.input.workspace_root,
        data_root=cfg.input.data_root,
        progress_callback=progress,
        report_renderer=report_renderer,
    )
    return SelectionRun(
        action=action,
        selection_id=cfg.selection_id,
        output_root=cfg.output_root,
        counts={
            "candidates": len(built.candidates),
            "selected": len(built.selection.selected),
            "rejected": len(built.selection.rejected),
        },
        outputs=dict(built.output_paths),
    )


def _run_plan(
    path: Path,
    cfg: SiteSelectionConfig,
    *,
    plan_report_renderer: ReportRenderer | None,
) -> SelectionRun:
    """Validate the file, then write the plan manifest and its report."""

    plan = plan_site_selection(path)
    outputs: dict[str, Path] = {}
    wants_report = cfg.output.write_report_html and plan_report_renderer is not None
    if cfg.input.write_plan_manifest or wants_report:
        outputs["plan_manifest"] = plan.write_manifest()
    if wants_report:
        outputs["site_selection_report_html"] = plan_report_renderer(outputs["plan_manifest"])
    return SelectionRun(
        action="plan",
        selection_id=cfg.selection_id,
        output_root=cfg.output_root,
        counts={},
        outputs=outputs,
    )


def _refuse_a_workflow_mode(raw: dict[str, Any]) -> None:
    """Refuse a selection file that still declares a workflow mode."""

    workflow = raw.get("workflow")
    if isinstance(workflow, dict) and "mode" in workflow:
        raise ConfigError(
            "[workflow] mode is not read by a site selection: hmp site select <file> "
            "runs it. Remove [workflow] mode from the file."
        )


def _resolve_action(cfg: SiteSelectionConfig, raw: dict[str, Any]) -> str:
    mode = cfg.input.mode

    if mode == "plan_only":
        return "plan"
    if mode in {"delineated_catchments", "generated_candidates", "dem_area_light"}:
        return mode
    if mode == "hydrometry":
        if not isinstance(raw.get("hydrometry"), dict):
            raise ConfigMissingError(
                "site_selection.input.mode='hydrometry' requires [hydrometry]."
            )
        return "hydrometry"

    raise ConfigError(f"Unsupported site_selection.input.mode={mode!r}.")


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


__all__ = [
    "PLAN_MANIFEST_NAME",
    "ReportRenderer",
    "SelectionRun",
    "SiteSelectionPlan",
    "build_dem_area_light_site_selection_from_toml",
    "build_generated_site_selection_from_toml",
    "build_observed_site_selection_from_toml",
    "build_site_selection_from_hydrometry_config",
    "load_data_dem_config_for_site_selection",
    "load_delineated_catchments_csv",
    "load_hydrometry_config_for_site_selection",
    "load_site_selection_config",
    "plan_site_selection",
    "run_site_selection",
    "select_delineated_catchments_from_csv",
]
