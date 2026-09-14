"""DEM path and request-bbox resolution helpers for the site-selection workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.core import progress
from hydromodpy.core.exceptions import (
    ConfigError,
    ConfigMissingError,
    ConfigValidationError,
)
from hydromodpy.core.toml_io.loader import load_toml_with_base_config
from hydromodpy.data.managers.config_schema import DataManagersConfig
from hydromodpy.data.variables.dem.config import DemConfig as DataDemConfig
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
from hydromodpy.spatial.site_selection.hydrology.delineation import (
    DelineatedCatchment,
    try_delineate_candidate_outlet,
)
from hydromodpy.spatial.site_selection.hydrology.flow_products import (
    FlowProductsBuilder,
    build_site_selection_flow_products,
)
from hydromodpy.workflow._site_selection_paths import _data_access_error
from hydromodpy.workflow.site_selection_data import DemLoader, load_dem_path


def _load_data_dem_config(path: str | Path) -> DataDemConfig | None:
    """Load an optional ``[data.dem]`` section for site-selection DEM resolution."""

    config_path = Path(path).expanduser().resolve()
    raw = load_toml_with_base_config(config_path)
    data_cfg = DataManagersConfig.from_toml_section(
        raw.get("data", {}),
        base_dir=config_path.parent,
    )
    return data_cfg.dem


def _data_dem_config_for_site_selection(
    *,
    config: SiteSelectionConfig,
    config_path: str | Path | None,
) -> DataDemConfig | None:
    """Return the explicit ``[data.dem]`` config or the source shorthand fallback."""

    if config_path is not None:
        data_dem_config = _load_data_dem_config(config_path)
        if data_dem_config is not None:
            return data_dem_config
    if config.dem.source == "ign_geoplateforme_dem":
        return DataDemConfig.ign_geoplateforme_dem(force_refresh=config.dem.force_refresh)
    return None


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
            reference_network_source=("" if reference_bundle is None else reference_bundle.source),
            reference_network_max_distance_m=config.outlets.reference_network_max_distance_m,
        )
        for catchment in progress.track(catchments, "Delineating catchments")
    ]
    flow_manifest = flow_products.to_manifest_record()
    flow_manifest["dem_path"] = str(dem_path)
    flow_manifest["dem_source"] = config.dem.source
    flow_manifest["intermediate_rasters_kept"] = config.output.keep_intermediate_rasters
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
    data_dem_config = _data_dem_config_for_site_selection(
        config=config,
        config_path=config_path,
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

    data_dem_config = _data_dem_config_for_site_selection(
        config=config,
        config_path=config_path,
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

    data_dem_config = _data_dem_config_for_site_selection(
        config=config,
        config_path=config_path,
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

    data_dem_config = _data_dem_config_for_site_selection(
        config=config,
        config_path=config_path,
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

    data_dem_config = _data_dem_config_for_site_selection(
        config=config,
        config_path=config_path,
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
