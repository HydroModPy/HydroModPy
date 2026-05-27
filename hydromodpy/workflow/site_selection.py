"""Lightweight workflow entry points for site selection."""

from __future__ import annotations

import csv
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from hydromodpy.core.exceptions import (
    ConfigError,
    ConfigMissingError,
    ConfigValidationError,
    DataContractViolation,
)
from hydromodpy.core.toml_io.loader import load_toml_with_base_config
from hydromodpy.data.data_managers_config import DataManagersConfig
from hydromodpy.data.variables.dem.config import DemConfig as DataDemConfig
from hydromodpy.data.variables.hydrometry.config import HydrometryConfig
from hydromodpy.spatial.geographic.core.catchment_from_point import (
    extract_catchment_from_point,
)
from hydromodpy.spatial.geographic.core.flow_products import build_regional_flow_products
from hydromodpy.spatial.site_selection.candidates.outlets import (
    CandidateOutlet,
    candidate_outlets_from_point_records,
)
from hydromodpy.spatial.site_selection.candidates.reference_network import (
    ReferenceNetworkBundle,
    load_reference_network_for_outlets,
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
    try_delineate_candidate_outlet,
)
from hydromodpy.spatial.site_selection.hydrology.flow_products import (
    FlowProductsBuilder,
    build_site_selection_flow_products,
)
from hydromodpy.spatial.site_selection.outputs.artifacts import write_manifest_and_optional_report
from hydromodpy.spatial.site_selection.outputs.pipeline import (
    write_core_site_selection_outputs,
)
from hydromodpy.spatial.site_selection.pipelines.build import (
    SiteSelectionBuildResult,
    build_site_selection_from_dem_area_light,
    build_site_selection_from_generated_network,
    build_site_selection_from_point_records,
)
from hydromodpy.spatial.site_selection.reports.plan import (
    render_site_selection_plan_html_report,
)
from hydromodpy.workflow.site_selection_data import (
    DemLoader,
    HydrometryLoader,
    load_dem_path,
    load_hydrometry_records,
)

PLAN_MANIFEST_NAME = "site_selection_plan.json"
ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class SiteSelectionPlan:
    """Validated plan produced before any heavy spatial computation."""

    config: SiteSelectionConfig
    manifest: dict[str, Any]

    def write_manifest(self, path: str | Path | None = None) -> Path:
        """Write the plan manifest as JSON."""

        destination = Path(path) if path is not None else self.config.output_root / PLAN_MANIFEST_NAME
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

    config_path = Path(path).expanduser().resolve()
    raw = load_toml_with_base_config(config_path)
    data_cfg = DataManagersConfig.from_toml_section(
        raw.get("data", {}),
        base_dir=config_path.parent,
    )
    return data_cfg.dem


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
            "candidate_mode": cfg.strategy.candidate_mode or cfg.outlets.candidate_mode,
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
            "resolution_m": cfg.dem.resolution_m,
            "cache_policy": cfg.dem.cache_policy,
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
            "ruleset": cfg.criteria.ruleset,
            "hard_reject": list(cfg.criteria.hard_reject),
            "warning": list(cfg.criteria.warning),
            "soft_score": list(cfg.criteria.soft_score),
            "report_only": list(cfg.criteria.report_only),
            "area_mode": cfg.criteria.area.mode,
            "geology_mode": cfg.criteria.geology.mode,
            "flow_station_mode": cfg.criteria.observations.flow_station_mode,
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
                area_range.model_dump(mode="json")
                for area_range in cfg.criteria.area.ranges
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
        )
    )
    return result, paths


def _maybe_delineate_from_outlets(
    *,
    catchments: list[DelineatedCatchment],
    config: SiteSelectionConfig,
    config_path: str | Path | None = None,
    backend: object | None = None,
    flow_products_builder: FlowProductsBuilder | None = None,
    delineation_builder=None,
    area_reader=None,
    dem_loader: DemLoader | None = None,
) -> tuple[list[DelineatedCatchment], dict[str, Any]]:
    if not config.input.delineate_from_outlets:
        return catchments, {}
    dem_path = _resolve_dem_path_for_delineation(
        config=config,
        catchments=catchments,
        config_path=config_path,
        dem_loader=dem_loader,
    )
    flow_products = build_site_selection_flow_products(
        dem_init_path=dem_path,
        output_dir=config.output_root / "flow_products",
        hydrology=config.hydrology,
        crs_project=_first_outlet_crs(catchments),
        backend=backend,
        builder=flow_products_builder or build_regional_flow_products,
    )
    reference_network, reference_bundle = _maybe_load_reference_network(
        config=config,
        catchments=catchments,
        target_crs=_first_outlet_crs(catchments),
    )
    delineated = [
        try_delineate_candidate_outlet(
            outlet=catchment.outlet,
            flow_products=flow_products,
            output_root=config.output_root / "catchments",
            snap_dist_m=config.outlets.snap_dist_m,
            crs_project=catchment.outlet.crs,
            site_id=catchment.site_id,
            backend=backend,
            builder=delineation_builder or extract_catchment_from_point,
            area_reader=area_reader,
            reference_network=reference_network,
            reference_network_source=(
                "" if reference_bundle is None else reference_bundle.source
            ),
            reference_network_max_distance_m=config.outlets.reference_network_max_distance_m,
        )
        for catchment in catchments
    ]
    flow_manifest = flow_products.to_manifest_record()
    flow_manifest["dem_path"] = str(dem_path)
    flow_manifest["dem_source"] = config.dem.source
    if reference_bundle is not None:
        flow_manifest["reference_network"] = reference_bundle.to_manifest_record()
    map_dem_path = _resolve_map_dem_path_for_review(
        config=config,
        catchments=catchments,
        config_path=config_path,
        delineation_dem_path=dem_path,
        dem_loader=dem_loader,
    )
    if map_dem_path is not None:
        flow_manifest["map_dem_path"] = str(map_dem_path)
    return delineated, flow_manifest


def _maybe_load_reference_network(
    *,
    config: SiteSelectionConfig,
    catchments: list[DelineatedCatchment],
    target_crs: str | None,
) -> tuple[object | None, ReferenceNetworkBundle | None]:
    if config.outlets.snap_strategy != "bdtopage_then_dem":
        return None, None
    if not target_crs:
        raise ConfigValidationError("bdtopage_then_dem requires a projected outlet CRS.")
    network, bundle = load_reference_network_for_outlets(
        source=config.outlets.reference_network_source,
        path=config.outlets.reference_network_path,
        outlets=[catchment.outlet for catchment in catchments],
        target_crs=target_crs,
        output_dir=config.output_root / "reference_network",
        fetch_margin_m=config.outlets.reference_network_fetch_margin_m,
        page_size=config.outlets.reference_network_page_size,
        force_refresh=config.outlets.reference_network_force_refresh,
    )
    return network, bundle


def _maybe_resolve_map_dem_for_review(
    *,
    config: SiteSelectionConfig,
    catchments: list[DelineatedCatchment],
    config_path: str | Path | None,
    dem_loader: DemLoader | None,
) -> dict[str, Any]:
    """Resolve a regional DEM background even when basins are pre-delineated."""

    if config.dem.map_background_extent == "none":
        return {}
    if config.dem.path is not None:
        return {
            "map_dem_path": str(Path(config.dem.path).expanduser().resolve()),
            "dem_source": config.dem.source,
            "dem_usage": "review_map_background",
        }
    data_dem_config: DataDemConfig | None = None
    if config_path is not None:
        data_dem_config = load_data_dem_config_for_site_selection(config_path)
    if data_dem_config is None and config.dem.source == "ign_geoplateforme_dem":
        data_dem_config = DataDemConfig.ign_geoplateforme_dem(
            force_refresh=config.dem.force_refresh
        )
    if data_dem_config is None:
        return {}
    map_dem_path = load_dem_path(
        data_dem_config,
        workspace_root=config.input.workspace_root,
        data_root=config.input.data_root,
        project_extent=_dem_request_bbox(
            config=config,
            catchments=catchments,
            request_extent="territory",
        ),
        loader=dem_loader,
    )
    return {
        "map_dem_path": str(map_dem_path),
        "dem_source": config.dem.source,
        "dem_usage": "review_map_background",
    }


def _resolve_dem_path_for_delineation(
    *,
    config: SiteSelectionConfig,
    catchments: list[DelineatedCatchment],
    config_path: str | Path | None,
    dem_loader: DemLoader | None,
) -> Path:
    if config.dem.path is not None:
        return Path(config.dem.path).expanduser().resolve()

    data_dem_config: DataDemConfig | None = None
    if config_path is not None:
        data_dem_config = load_data_dem_config_for_site_selection(config_path)

    if data_dem_config is None and config.dem.source == "ign_geoplateforme_dem":
        data_dem_config = DataDemConfig.ign_geoplateforme_dem(
            force_refresh=config.dem.force_refresh
        )

    if data_dem_config is None:
        raise ConfigMissingError(
            "site_selection.input.delineate_from_outlets=true requires either "
            "site_selection.dem.path or a [data.dem] source."
        )

    return load_dem_path(
        data_dem_config,
        workspace_root=config.input.workspace_root,
        data_root=config.input.data_root,
        project_extent=_dem_request_bbox(
            config=config,
            catchments=catchments,
            request_extent=config.dem.request_extent,
        ),
        loader=dem_loader,
    )


def _resolve_dem_path_for_observed_selection(
    *,
    config: SiteSelectionConfig,
    config_path: str | Path | None,
    workspace_root: str | Path | None,
    data_root: str | Path | None,
    dem_loader: DemLoader | None,
    candidate_outlets: list[CandidateOutlet] | None = None,
) -> Path:
    """Resolve the DEM used to derive flow products for station-led selection."""

    if config.dem.path is not None:
        return Path(config.dem.path).expanduser().resolve()

    data_dem_config: DataDemConfig | None = None
    if config_path is not None:
        data_dem_config = load_data_dem_config_for_site_selection(config_path)

    if data_dem_config is None and config.dem.source == "ign_geoplateforme_dem":
        data_dem_config = DataDemConfig.ign_geoplateforme_dem(
            force_refresh=config.dem.force_refresh
        )

    if data_dem_config is None:
        raise ConfigMissingError(
            "site_selection.input.mode='hydrometry' requires either "
            "site_selection.dem.path or a [data.dem] source so station outlets "
            "can be delineated from a DEM."
        )

    try:
        return load_dem_path(
            data_dem_config,
            workspace_root=workspace_root,
            data_root=data_root,
            project_extent=_observed_dem_request_bbox(
                config=config,
                candidate_outlets=candidate_outlets or [],
            ),
            loader=dem_loader,
        )
    except Exception as exc:
        raise ConfigError(_data_access_error("DEM", data_root=data_root, detail=exc)) from exc


def _resolve_dem_path_for_generated_selection(
    *,
    config: SiteSelectionConfig,
    config_path: str | Path | None,
    workspace_root: str | Path | None,
    data_root: str | Path | None,
    dem_loader: DemLoader | None,
) -> Path:
    """Resolve the DEM used to generate network candidates."""

    if config.dem.path is not None:
        return Path(config.dem.path).expanduser().resolve()

    data_dem_config: DataDemConfig | None = None
    if config_path is not None:
        data_dem_config = load_data_dem_config_for_site_selection(config_path)

    if data_dem_config is None and config.dem.source == "ign_geoplateforme_dem":
        data_dem_config = DataDemConfig.ign_geoplateforme_dem(
            force_refresh=config.dem.force_refresh
        )

    if data_dem_config is None:
        raise ConfigMissingError(
            "site_selection.input.mode='generated_candidates' or 'dem_area_light' requires either "
            "site_selection.dem.path or a [data.dem] source."
        )

    try:
        return load_dem_path(
            data_dem_config,
            workspace_root=workspace_root,
            data_root=data_root,
            project_extent=_dem_request_bbox(
                config=config,
                catchments=[],
                request_extent="territory",
            ),
            loader=dem_loader,
        )
    except Exception as exc:
        raise ConfigError(_data_access_error("DEM", data_root=data_root, detail=exc)) from exc


def _resolve_map_dem_path_for_review(
    *,
    config: SiteSelectionConfig,
    catchments: list[DelineatedCatchment],
    config_path: str | Path | None,
    delineation_dem_path: Path,
    dem_loader: DemLoader | None,
) -> Path | None:
    mode = config.dem.map_background_extent
    if mode == "none":
        return None
    if mode == "delineation":
        return delineation_dem_path

    data_dem_config: DataDemConfig | None = None
    if config_path is not None:
        data_dem_config = load_data_dem_config_for_site_selection(config_path)
    if data_dem_config is None and config.dem.source == "ign_geoplateforme_dem":
        data_dem_config = DataDemConfig.ign_geoplateforme_dem(
            force_refresh=config.dem.force_refresh
        )
    if data_dem_config is None:
        return delineation_dem_path

    return load_dem_path(
        data_dem_config,
        workspace_root=config.input.workspace_root,
        data_root=config.input.data_root,
        project_extent=_dem_request_bbox(
            config=config,
            catchments=catchments,
            request_extent="territory",
        ),
        loader=dem_loader,
    )


def _dem_request_bbox(
    *,
    config: SiteSelectionConfig,
    catchments: list[DelineatedCatchment],
    request_extent: str,
) -> tuple[float, float, float, float] | None:
    margin_m = float(config.dem.margin_km or 0.0) * 1000.0
    if request_extent == "outlets" and catchments:
        return _outlet_bbox(catchments, margin_m=margin_m)

    territory = config.territory
    if territory.mode == "bbox" and territory.bbox is not None:
        return _expand_projected_bbox(tuple(territory.bbox), margin_m)
    if territory.country in {None, "", "FR"}:
        if territory.mode == "admin_regions":
            from hydromodpy.data.common.administrative.france import bbox_for_regions

            return bbox_for_regions(territory.regions, margin_m=margin_m)
        if territory.mode == "admin_departments":
            from hydromodpy.data.common.administrative.france import bbox_for_departments

            return bbox_for_departments(territory.departments, margin_m=margin_m)
    if territory.mode == "polygon_file" and territory.polygon_file is not None:
        import geopandas as gpd

        gdf = gpd.read_file(territory.polygon_file)
        if gdf.crs is not None and gdf.crs.to_epsg() != 2154:
            gdf = gdf.to_crs("EPSG:2154")
        return _expand_projected_bbox(tuple(float(v) for v in gdf.total_bounds), margin_m)
    if catchments:
        return _outlet_bbox(catchments, margin_m=margin_m)
    return None


def _observed_dem_request_bbox(
    *,
    config: SiteSelectionConfig,
    candidate_outlets: list[CandidateOutlet],
) -> tuple[float, float, float, float] | None:
    margin_m = float(config.dem.margin_km or 0.0) * 1000.0
    if config.dem.request_extent == "outlets" and candidate_outlets:
        return _candidate_outlet_bbox(candidate_outlets, margin_m=margin_m)
    return _dem_request_bbox(
        config=config,
        catchments=[],
        request_extent=config.dem.request_extent,
    )


def _candidate_outlets_for_dem_request(
    config: SiteSelectionConfig,
    records: list[Any],
) -> list[CandidateOutlet]:
    if config.dem.request_extent != "outlets":
        return []
    target_crs = _default_project_crs_for_selection(config)
    if target_crs is None:
        return []
    return candidate_outlets_from_point_records(
        records,
        candidate_prefix="station",
        source="station_outlets",
        target_crs=target_crs,
    )


def _default_project_crs_for_selection(config: SiteSelectionConfig) -> str | None:
    if (config.territory.country or "").upper() == "FR":
        return "EPSG:2154"
    return None


def _observation_request_bbox_wgs84(
    config: SiteSelectionConfig,
) -> tuple[float, float, float, float] | None:
    """Return a WGS84 bbox for observation APIs from the project territory."""

    bbox = _dem_request_bbox(config=config, catchments=[], request_extent="territory")
    if bbox is None:
        return None
    return _bbox_projected_to_wgs84(bbox)


def _bbox_projected_to_wgs84(
    bbox: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """Transform a Lambert-93 bbox to WGS84 for French observation APIs."""

    try:
        from pyproj import Transformer
    except ImportError as exc:  # pragma: no cover - pyproj is part of spatial deps.
        raise ImportError("pyproj is required to query observation APIs by territory.") from exc

    transformer = Transformer.from_crs("EPSG:2154", "EPSG:4326", always_xy=True)
    xmin, ymin, xmax, ymax = bbox
    corners = [
        transformer.transform(xmin, ymin),
        transformer.transform(xmin, ymax),
        transformer.transform(xmax, ymin),
        transformer.transform(xmax, ymax),
    ]
    xs = [float(x) for x, _y in corners]
    ys = [float(y) for _x, y in corners]
    return (min(xs), min(ys), max(xs), max(ys))


def _outlet_bbox(
    catchments: list[DelineatedCatchment],
    *,
    margin_m: float,
) -> tuple[float, float, float, float]:
    xs = [catchment.outlet.x for catchment in catchments]
    ys = [catchment.outlet.y for catchment in catchments]
    return _expand_projected_bbox((min(xs), min(ys), max(xs), max(ys)), margin_m)


def _candidate_outlet_bbox(
    candidate_outlets: list[CandidateOutlet],
    *,
    margin_m: float,
) -> tuple[float, float, float, float]:
    xs = [candidate.x for candidate in candidate_outlets]
    ys = [candidate.y for candidate in candidate_outlets]
    return _expand_projected_bbox((min(xs), min(ys), max(xs), max(ys)), margin_m)


def _expand_projected_bbox(
    bbox: tuple[float, float, float, float],
    margin_m: float,
) -> tuple[float, float, float, float]:
    if margin_m <= 0:
        return bbox
    xmin, ymin, xmax, ymax = bbox
    return (xmin - margin_m, ymin - margin_m, xmax + margin_m, ymax + margin_m)


def _first_outlet_crs(catchments: list[DelineatedCatchment]) -> str | None:
    for catchment in catchments:
        if catchment.outlet.crs:
            return catchment.outlet.crs
    return None


def _emit_progress(callback: ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def _stderr_progress(message: str) -> None:
    print(f"[site_selection] {message}", file=sys.stderr)


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


def run_site_selection_workflow(config_path: str | Path) -> dict[str, Any]:
    """Run the lightweight ``site_selection`` workflow declared in a TOML file."""

    path = Path(config_path).expanduser().resolve()
    raw = load_toml_with_base_config(path)
    cfg = load_site_selection_config(path)
    action = _resolve_workflow_action(cfg, raw)

    if action == "plan":
        plan = plan_site_selection(path)
        manifest_path = plan.write_manifest() if cfg.input.write_plan_manifest else None
        report_path = None
        if cfg.output.write_report_html:
            if manifest_path is None:
                manifest_path = plan.write_manifest()
            report_path = render_site_selection_plan_html_report(manifest_path)
        return {
            "action": "plan",
            "selection_id": cfg.selection_id,
            "output_root": str(cfg.output_root),
            "plan_manifest": "" if manifest_path is None else str(manifest_path),
            "site_selection_report_html": "" if report_path is None else str(report_path),
        }

    if action == "delineated_catchments":
        if cfg.input.catchments_csv is None:
            raise ConfigMissingError("site_selection.input.catchments_csv is required.")
        result, paths = select_delineated_catchments_from_csv(
            config_path=path,
            catchments_csv=cfg.input.catchments_csv,
            region_id=cfg.input.region_id,
        )
        return {
            "action": "delineated_catchments",
            "selection_id": cfg.selection_id,
            "selected": len(result.selected),
            "rejected": len(result.rejected),
            "selected_sites_csv": str(paths.get("selected_sites_csv", "")),
            "regional_lab_sites_csv": str(paths.get("regional_lab_sites_csv", "")),
            "selected_outlets_geojson": str(paths.get("selected_outlets_geojson", "")),
            "rejected_outlets_geojson": str(paths.get("rejected_outlets_geojson", "")),
            "selected_basins_geojson": str(paths.get("selected_basins_geojson", "")),
            "rejected_basins_geojson": str(paths.get("rejected_basins_geojson", "")),
            "observation_points_geojson": str(paths.get("observation_points_geojson", "")),
            "site_selection_manifest_json": str(
                paths.get("site_selection_manifest_json", "")
            ),
            "site_selection_report_html": str(paths.get("site_selection_report_html", "")),
            "site_selection_map_png": str(paths.get("site_selection_map_png", "")),
        }

    if action == "generated_candidates":
        if cfg.outlets.candidate_mode != "network_sampling":
            raise ConfigError(
                "site_selection.input.mode='generated_candidates' requires "
                "site_selection.outlets.candidate_mode='network_sampling'."
            )
        result = build_generated_site_selection_from_toml(
            config_path=path,
            workspace_root=cfg.input.workspace_root,
            data_root=cfg.input.data_root,
            progress_callback=_stderr_progress,
        )
        return {
            "action": "generated_candidates",
            "selection_id": cfg.selection_id,
            "candidates": len(result.candidates),
            "selected": len(result.selection.selected),
            "rejected": len(result.selection.rejected),
            "candidate_generation_jsonl": str(
                result.output_paths.get("candidate_generation_jsonl", "")
            ),
            "candidate_outlets_geojson": str(
                result.output_paths.get("candidate_outlets_geojson", "")
            ),
            "generated_network_geojson": str(
                result.output_paths.get("generated_network_geojson", "")
            ),
            "selected_sites_csv": str(result.output_paths.get("selected_sites_csv", "")),
            "regional_lab_sites_csv": str(
                result.output_paths.get("regional_lab_sites_csv", "")
            ),
            "selected_outlets_geojson": str(
                result.output_paths.get("selected_outlets_geojson", "")
            ),
            "selected_basins_geojson": str(
                result.output_paths.get("selected_basins_geojson", "")
            ),
            "site_selection_manifest_json": str(
                result.output_paths.get("site_selection_manifest_json", "")
            ),
            "site_selection_report_html": str(
                result.output_paths.get("site_selection_report_html", "")
            ),
            "site_selection_map_png": str(
                result.output_paths.get("site_selection_map_png", "")
            ),
        }

    if action == "dem_area_light":
        result = build_dem_area_light_site_selection_from_toml(
            config_path=path,
            workspace_root=cfg.input.workspace_root,
            data_root=cfg.input.data_root,
            progress_callback=_stderr_progress,
        )
        return {
            "action": "dem_area_light",
            "selection_id": cfg.selection_id,
            "candidates": len(result.candidates),
            "selected": len(result.selection.selected),
            "rejected": len(result.selection.rejected),
            "candidate_generation_jsonl": str(
                result.output_paths.get("candidate_generation_jsonl", "")
            ),
            "candidate_outlets_geojson": str(
                result.output_paths.get("candidate_outlets_geojson", "")
            ),
            "diagnostics_csv": str(result.output_paths.get("diagnostics_csv", "")),
            "selected_sites_csv": str(result.output_paths.get("selected_sites_csv", "")),
            "regional_lab_sites_csv": str(
                result.output_paths.get("regional_lab_sites_csv", "")
            ),
            "selected_outlets_geojson": str(
                result.output_paths.get("selected_outlets_geojson", "")
            ),
            "selected_basins_geojson": str(
                result.output_paths.get("selected_basins_geojson", "")
            ),
            "site_selection_manifest_json": str(
                result.output_paths.get("site_selection_manifest_json", "")
            ),
            "site_selection_report_html": str(
                result.output_paths.get("site_selection_report_html", "")
            ),
            "site_selection_map_png": str(
                result.output_paths.get("site_selection_map_png", "")
            ),
        }

    if cfg.strategy.principle != "observation_led":
        raise ConfigError(
            "site_selection input mode 'hydrometry' currently requires "
            "strategy.principle='observation_led'."
        )
    result = build_observed_site_selection_from_toml(
        config_path=path,
        workspace_root=cfg.input.workspace_root,
        data_root=cfg.input.data_root,
        progress_callback=_stderr_progress,
    )
    return {
        "action": "hydrometry",
        "selection_id": cfg.selection_id,
        "candidates": len(result.candidates),
        "selected": len(result.selection.selected),
        "rejected": len(result.selection.rejected),
        "selected_sites_csv": str(result.output_paths.get("selected_sites_csv", "")),
        "regional_lab_sites_csv": str(result.output_paths.get("regional_lab_sites_csv", "")),
        "selected_outlets_geojson": str(
            result.output_paths.get("selected_outlets_geojson", "")
        ),
        "rejected_outlets_geojson": str(
            result.output_paths.get("rejected_outlets_geojson", "")
        ),
        "selected_basins_geojson": str(
            result.output_paths.get("selected_basins_geojson", "")
        ),
        "rejected_basins_geojson": str(
            result.output_paths.get("rejected_basins_geojson", "")
        ),
        "observation_points_geojson": str(
            result.output_paths.get("observation_points_geojson", "")
        ),
        "site_selection_manifest_json": str(
            result.output_paths.get("site_selection_manifest_json", "")
        ),
        "site_selection_report_html": str(
            result.output_paths.get("site_selection_report_html", "")
        ),
        "site_selection_map_png": str(result.output_paths.get("site_selection_map_png", "")),
    }


def _resolve_paths(cfg: SiteSelectionConfig, *, base_dir: Path) -> SiteSelectionConfig:
    output_root = _resolve_optional_path(cfg.output_root, base_dir=base_dir)
    dem = cfg.dem
    dem_path = _resolve_optional_path(dem.path, base_dir=base_dir)
    outlets = cfg.outlets
    reference_network_path = _resolve_optional_path(
        outlets.reference_network_path,
        base_dir=base_dir,
    )
    territory = cfg.territory
    polygon_file = _resolve_optional_path(territory.polygon_file, base_dir=base_dir)
    input_cfg = cfg.input
    catchments_csv = _resolve_optional_path(input_cfg.catchments_csv, base_dir=base_dir)
    workspace_root = _resolve_optional_path(input_cfg.workspace_root, base_dir=base_dir)
    data_root = _resolve_optional_path(input_cfg.data_root, base_dir=base_dir)
    map_context = cfg.map_context
    context_layers = [
        layer.model_copy(update={"path": _resolve_optional_path(layer.path, base_dir=base_dir)})
        for layer in map_context.layers
    ]
    criteria = cfg.criteria
    influence = criteria.influence
    influence_layers = [
        layer.model_copy(update={"path": _resolve_optional_path(layer.path, base_dir=base_dir)})
        for layer in influence.layers
    ]
    geology = criteria.geology
    geology_layers = [
        layer.model_copy(update={"path": _resolve_optional_path(layer.path, base_dir=base_dir)})
        for layer in geology.layers
    ]
    observations = criteria.observations
    piezometer_layers = [
        layer.model_copy(update={"path": _resolve_optional_path(layer.path, base_dir=base_dir)})
        for layer in observations.piezometer_layers
    ]
    return cfg.model_copy(
        update={
            "output_root": output_root,
            "dem": dem.model_copy(update={"path": dem_path}),
            "outlets": outlets.model_copy(
                update={"reference_network_path": reference_network_path}
            ),
            "territory": territory.model_copy(update={"polygon_file": polygon_file}),
            "input": input_cfg.model_copy(
                update={
                    "catchments_csv": catchments_csv,
                    "workspace_root": workspace_root,
                    "data_root": data_root,
                }
            ),
            "criteria": criteria.model_copy(
                update={
                    "influence": influence.model_copy(update={"layers": influence_layers}),
                    "geology": geology.model_copy(update={"layers": geology_layers}),
                    "observations": observations.model_copy(
                        update={"piezometer_layers": piezometer_layers}
                    ),
                }
            ),
            "map_context": map_context.model_copy(update={"layers": context_layers}),
        },
    )


def _with_default_data_root(
    cfg: SiteSelectionConfig,
    data_root: str | Path | None = None,
) -> SiteSelectionConfig:
    """Return ``cfg`` with an isolated default data root for executable runs."""

    resolved_data_root = (
        Path(data_root).expanduser().resolve()
        if data_root is not None
        else cfg.input.data_root or cfg.output_root / "data"
    )
    return cfg.model_copy(
        update={"input": cfg.input.model_copy(update={"data_root": resolved_data_root})}
    )


def _data_access_error(
    family: str,
    *,
    data_root: str | Path | None,
    detail: Exception,
) -> str:
    root = "<default>" if data_root is None else str(Path(data_root).expanduser())
    section = "[hydrometry]" if family == "hydrometry" else "[data.dem]"
    return (
        f"site_selection failed while loading {family} data. "
        f"data_root={root}. Check [site_selection.input].data_root, the matching "
        f"{section} TOML section, and provider cache permissions. "
        f"Original error: {type(detail).__name__}: {detail}"
    )


def _resolve_optional_path(path: Path | None, *, base_dir: Path) -> Path | None:
    if path is None:
        return None
    expanded = Path(path).expanduser()
    if expanded.is_absolute():
        return expanded
    return (base_dir / expanded).resolve()


def _resolve_csv_path(value: object, *, base_dir: Path) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    if path.is_absolute():
        return str(path)
    return str((base_dir / path).resolve())


def _path_or_none(path: Path | None) -> str | None:
    return None if path is None else str(path)


def _resolve_workflow_action(cfg: SiteSelectionConfig, raw: dict[str, Any]) -> str:
    mode = cfg.input.mode

    if mode == "plan_only":
        return "plan"
    if mode == "delineated_catchments":
        return "delineated_catchments"
    if mode == "generated_candidates":
        return "generated_candidates"
    if mode == "dem_area_light":
        return "dem_area_light"
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
    if cfg.output.write_regional_lab_csv:
        outputs.append("regional_lab_csv")
    if cfg.output.write_report_html:
        outputs.append("report_html")
    return outputs


def _required_text(row: dict[str, str], field: str, *, row_number: int) -> str:
    value = str(row.get(field) or "").strip()
    if not value:
        raise DataContractViolation(
            f"catchments CSV row {row_number} is missing required field {field!r}."
        )
    return value


def _float_from_row(
    row: dict[str, str],
    field: str,
    *,
    fallback_field: str,
    row_number: int,
) -> float:
    value = row.get(field)
    if value in {None, ""}:
        value = row.get(fallback_field)
    number = _optional_float(value)
    if number is None:
        raise DataContractViolation(
            f"catchments CSV row {row_number} is missing numeric {field!r} "
            f"or fallback {fallback_field!r}."
        )
    return number


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    return float(text)


__all__ = [
    "PLAN_MANIFEST_NAME",
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
    "run_site_selection_workflow",
    "select_delineated_catchments_from_csv",
]
