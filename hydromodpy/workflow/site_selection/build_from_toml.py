"""Build a site selection from a project TOML, one entry point per workflow mode.

Each builder reads the tables it needs, loads the data through the data
managers and runs the spatial selection.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.logging import get_logger
from hydromodpy.data.sites.importers import fetch_bdtopage_reference_network
from hydromodpy.data.variables.hydrometry.config import HydrometryConfig
from hydromodpy.spatial.site_selection.config.site_selection_config import SiteSelectionConfig
from hydromodpy.spatial.site_selection.hydrology.flow_products import FlowProductsBuilder
from hydromodpy.spatial.site_selection.pipelines.build import (
    SiteSelectionBuildResult,
    build_site_selection_from_dem_area_light,
    build_site_selection_from_generated_network,
    build_site_selection_from_point_records,
)
from hydromodpy.workflow.site_selection.config_paths import (
    data_access_error,
    with_default_data_root,
)
from hydromodpy.workflow.site_selection.data_loading import (
    DemLoader,
    HydrometryLoader,
    load_hydrometry_config_for_site_selection,
    load_hydrometry_records,
    load_site_selection_config,
)
from hydromodpy.workflow.site_selection.dem_request import (
    BBox,
    candidate_outlets_for_dem_request,
    dem_request_bbox,
    observation_request_bbox_wgs84,
    observed_dem_request_bbox,
    resolve_dem_path,
)
from hydromodpy.workflow.site_selection.selection_plan import (
    ProgressCallback,
    ReportRenderer,
    format_project_extent,
)

__all__ = [
    "build_dem_area_light_site_selection_from_toml",
    "build_generated_site_selection_from_toml",
    "build_observed_site_selection_from_toml",
    "build_site_selection_from_hydrometry_config",
]


logger = get_logger(__name__)


_MISSING_GENERATION_DEM = (
    "site_selection.input.mode='generated_candidates' or 'dem_area_light' requires either "
    "site_selection.dem.path or a [data.dem] source."
)


def _emit_progress(callback: ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def log_progress(message: str) -> None:
    logger.debug("[site_selection] %s", message)


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
        raise ConfigError(data_access_error("hydrometry", data_root=data_root, detail=exc)) from exc
    build_kwargs.setdefault("reference_network_fetcher", fetch_bdtopage_reference_network)
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

    path, cfg = _selection_config_for_run(config_path, output_root, data_root)
    hydrometry_cfg = load_hydrometry_config_for_site_selection(path)
    observation_extent = project_extent or observation_request_bbox_wgs84(cfg)
    _emit_progress(
        progress_callback,
        (
            f"{cfg.selection_id}: loading hydrometry records "
            f"for extent {format_project_extent(observation_extent)}"
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
            data_access_error("hydrometry", data_root=cfg.input.data_root, detail=exc)
        ) from exc
    _emit_progress(progress_callback, f"{cfg.selection_id}: loaded {len(records)} records")
    candidate_outlets = candidate_outlets_for_dem_request(cfg, records)
    dem_extent = observed_dem_request_bbox(
        config=cfg,
        candidate_outlets=candidate_outlets,
    )
    if candidate_outlets:
        _emit_progress(
            progress_callback,
            (
                f"{cfg.selection_id}: DEM extent from {len(candidate_outlets)} "
                f"station outlets {format_project_extent(dem_extent)}"
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
    return _build_on_the_dem(
        build_site_selection_from_point_records,
        path=path,
        cfg=cfg,
        workspace_root=workspace_root,
        dem_loader=dem_loader,
        dem_extent=lambda: dem_extent,
        missing_dem=(
            "site_selection.input.mode='hydrometry' requires either "
            "site_selection.dem.path or a [data.dem] source so station outlets "
            "can be delineated from a DEM."
        ),
        step="building flow products, catchments and report artifacts",
        progress_callback=progress_callback,
        point_records=records,
        reference_network_fetcher=fetch_bdtopage_reference_network,
        backend=backend,
        flow_products_builder=flow_products_builder,
        delineation_builder=delineation_builder,
        area_reader=area_reader,
        write_outputs=write_outputs,
        report_renderer=report_renderer,
    )


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

    path, cfg = _selection_config_for_run(config_path, output_root, data_root)
    return _build_on_the_dem(
        build_site_selection_from_generated_network,
        path=path,
        cfg=cfg,
        workspace_root=workspace_root,
        dem_loader=dem_loader,
        dem_extent=lambda: _territory_dem_extent(cfg),
        missing_dem=_MISSING_GENERATION_DEM,
        step="generating candidates, catchments and report artifacts",
        progress_callback=progress_callback,
        reference_network_fetcher=fetch_bdtopage_reference_network,
        backend=backend,
        flow_products_builder=flow_products_builder,
        delineation_builder=delineation_builder,
        area_reader=area_reader,
        write_outputs=write_outputs,
        report_renderer=report_renderer,
    )


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

    path, cfg = _selection_config_for_run(config_path, output_root, data_root)
    return _build_on_the_dem(
        build_site_selection_from_dem_area_light,
        path=path,
        cfg=cfg,
        workspace_root=workspace_root,
        dem_loader=dem_loader,
        dem_extent=lambda: _territory_dem_extent(cfg),
        missing_dem=_MISSING_GENERATION_DEM,
        step="scanning DEM area candidates and building report artifacts",
        progress_callback=progress_callback,
        backend=backend,
        flow_products_builder=flow_products_builder,
        raw_accumulation_builder=raw_accumulation_builder,
        delineation_builder=delineation_builder,
        area_reader=area_reader,
        write_outputs=write_outputs,
        report_renderer=report_renderer,
    )


def _selection_config_for_run(
    config_path: str | Path,
    output_root: str | Path | None,
    data_root: str | Path | None,
) -> tuple[Path, SiteSelectionConfig]:
    """Load the selection file with its output root and its data root for a run."""

    path = Path(config_path).expanduser().resolve()
    cfg = load_site_selection_config(path)
    target_root = Path(output_root).expanduser().resolve() if output_root else cfg.output_root
    cfg = with_default_data_root(
        cfg.model_copy(update={"output_root": target_root}),
        data_root,
    )
    return path, cfg


def _territory_dem_extent(cfg: SiteSelectionConfig) -> BBox | None:
    return dem_request_bbox(config=cfg, catchments=[], request_extent="territory")


def _build_on_the_dem(
    build: Callable[..., SiteSelectionBuildResult],
    *,
    path: Path,
    cfg: SiteSelectionConfig,
    workspace_root: str | Path | None,
    dem_loader: DemLoader | None,
    dem_extent: Callable[[], BBox | None],
    missing_dem: str,
    step: str,
    progress_callback: ProgressCallback | None,
    **build_kwargs: Any,
) -> SiteSelectionBuildResult:
    """Resolve the calculation DEM, run *build* on it and report its counts."""

    _emit_progress(progress_callback, f"{cfg.selection_id}: resolving calculation DEM")
    dem_path = resolve_dem_path(
        config=cfg,
        config_path=path,
        workspace_root=workspace_root or cfg.input.workspace_root,
        data_root=cfg.input.data_root,
        dem_loader=dem_loader,
        project_extent=dem_extent,
        missing=missing_dem,
    )
    _emit_progress(progress_callback, f"{cfg.selection_id}: calculation DEM ready: {dem_path}")
    _emit_progress(progress_callback, f"{cfg.selection_id}: {step}")
    result = build(config=cfg, dem_init_path=dem_path, **build_kwargs)
    _emit_progress(
        progress_callback,
        (
            f"{cfg.selection_id}: finished with {len(result.candidates)} candidates, "
            f"{len(result.selection.selected)} selected, "
            f"{len(result.selection.rejected)} rejected"
        ),
    )
    return result
