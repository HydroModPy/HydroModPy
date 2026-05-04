"""Assemble the full geographic artifact set from one config + workspace.

Builds the runtime payload consumed by ``CatchmentDelineation``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
from geopy.geocoders import Nominatim

from hydromodpy.spatial.geographic.core.catchment_domain import CatchmentDomainProducts
from hydromodpy.spatial.geographic.core.catchment_metrics import compute_catchment_area_km2
from hydromodpy.spatial.geographic.core.direct_dem_domain import build_direct_dem_domain
from hydromodpy.spatial.geographic.core.flow_products import (
    FlowProducts,
    build_regional_flow_products,
)
from hydromodpy.spatial.geographic.core.pipeline_steps import (
    build_standard_catchment,
    build_standard_domain_polygons,
    prepare_geographic_run,
)
from hydromodpy.spatial.geographic.core.river_network import (
    RiverNetworkProducts,
    _build_river_mesh_trace_from_network_gdf,
    build_river_network_products,
)
from hydromodpy.spatial.geographic.dem_metadata import (
    DemMetadata,
    read_dem_metadata,
)
from hydromodpy.spatial.geographic.domain_rasters import (
    DomainRasterProducts,
    build_domain_rasters,
)
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.spatial.geographic.geographic_io import resolve_delineation_backend
from hydromodpy.spatial.geographic.geographic_paths import GeographicPaths

_GEOGRAPHIC_CACHE_SCHEMA_VERSION = "hydromodpy_geographic_cache_v1"


@dataclass(frozen=True)
class _CachedGeographicProducts:
    """Artifact views reconstructed from one validated geographic cache hit."""

    flow_products: FlowProducts
    domain_products: CatchmentDomainProducts
    raster_products: DomainRasterProducts
    river_network_products: RiverNetworkProducts
    catchment_area_km2: float


@dataclass(frozen=True)
class GeographicRuntimeContext:
    """Compatibility payload produced by geographic preprocessing.

    The context groups canonical paths, regional flow products, clipped rasters,
    DEM metadata, optional river-network products, and area/CRS information.
    ``CatchmentDelineation`` converts it to public runtime attributes through
    ``runtime_attributes``.
    """

    paths: GeographicPaths
    flow_products: FlowProducts
    raster_products: DomainRasterProducts
    dem_metadata: DemMetadata
    river_network_products: RiverNetworkProducts
    catchment_area_km2: float
    crs_project: str | None
    epsg: int | None
    dem_res: float

    def runtime_attributes(self) -> dict[str, object]:
        """Return the public attribute payload expected from ``CatchmentDelineation``."""
        attrs = dict(vars(self.paths))
        attrs.update(
            {
                "hydrographic_network_generated_shp": self.paths.hydrographic_network_generated_shp,
                "hydrographic_network_generated_summary_json": (
                    self.paths.hydrographic_network_generated_summary_json
                ),
                "catch_area": float(self.catchment_area_km2),
                "crs_proj": self.crs_project,
                "epsg": self.epsg,
                "dem_res": self.dem_res,
                "_paths": self.paths,
                "_dem_metadata": self.dem_metadata,
                "_river_network_products": self.river_network_products,
                "river_mesh_trace": self.river_network_products.river_mesh_trace,
            }
        )
        attrs.update(self.dem_metadata.runtime_attributes())
        return attrs


def _geographic_cache_manifest_path(paths: GeographicPaths) -> Path:
    """Return the cache manifest path for one geographic workspace."""
    return Path(paths.geographic_path) / "_geographic_cache_manifest.json"


def _path_signature(path: str | Path | None) -> dict[str, object] | None:
    """Return a compact invalidation signature for one optional input path."""
    if path is None:
        return None
    path_obj = Path(path).expanduser()
    if not path_obj.exists():
        return {"path": str(path_obj), "exists": False}
    stat = path_obj.stat()
    return {
        "path": str(path_obj.resolve()),
        "exists": True,
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def _geographic_cache_fingerprint(config: GeographicConfig) -> str:
    """Build a deterministic fingerprint for geographic preprocessing inputs."""
    config_payload = config.model_dump(mode="json")
    # This flag controls cache use; it should not invalidate the underlying
    # generated artifacts when toggled.
    config_payload.pop("reuse_existing_outputs", None)
    payload = {
        "schema": _GEOGRAPHIC_CACHE_SCHEMA_VERSION,
        "config": config_payload,
        "inputs": {
            "dem_init_path": _path_signature(config.dem_init_path),
            "polyg_shp_path": _path_signature(config.polyg_shp_path),
            "bottom_path": _path_signature(config.bottom_path),
        },
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _vector_artifact_exists(path: str | Path) -> bool:
    """Return true when a vector artifact is present enough to be reopened."""
    vector_path = Path(path)
    if vector_path.suffix.lower() != ".shp":
        return vector_path.exists()
    return all(vector_path.with_suffix(suffix).exists() for suffix in (".shp", ".shx", ".dbf"))


def _all_artifacts_exist(paths: list[str | Path]) -> bool:
    """Return true when every declared raster/vector artifact exists."""
    for raw_path in paths:
        path = Path(raw_path)
        if path.suffix.lower() == ".shp":
            if not _vector_artifact_exists(path):
                return False
            continue
        if not path.exists():
            return False
    return True


def _flow_products_from_paths(paths: GeographicPaths, dem_correc_type: str) -> FlowProducts:
    """Reconstruct the flow-products view from canonical cache paths."""
    correc_name = "dem_fill.tif" if dem_correc_type == "fill" else "dem_breach.tif"
    correc = str(Path(paths.correcflow_path) / correc_name)
    return FlowProducts(
        correc=correc,
        direc=str(Path(paths.correcflow_path) / "dem_direc.tif"),
        acc=str(Path(paths.correcflow_path) / "dem_acc.tif"),
    )


def _raster_products_from_paths(paths: GeographicPaths) -> DomainRasterProducts:
    """Reconstruct the legacy raster-products view from canonical cache paths."""
    return DomainRasterProducts(
        watershed_box_buff_dem=paths.watershed_box_buff_dem,
        watershed_box_buff_fill=paths.watershed_box_buff_fill,
        watershed_box_buff_direc=paths.watershed_box_buff_direc,
        watershed_buff_dem=paths.watershed_buff_dem,
        watershed_buff_fill=paths.watershed_buff_fill,
        watershed_buff_direc=paths.watershed_buff_direc,
        watershed_dem=paths.watershed_dem,
        watershed_fill=paths.watershed_fill,
        watershed_direc=paths.watershed_direc,
        watershed_contour_tif=paths.watershed_contour_tif,
    )


def _river_products_from_cache(
    *,
    config: GeographicConfig,
    paths: GeographicPaths,
    crs_project: str | None,
) -> RiverNetworkProducts:
    """Reconstruct river-network products from existing files when enabled."""
    if not bool(config.river_network.enabled):
        return RiverNetworkProducts(enabled=False)

    summary_path = Path(paths.hydrographic_network_generated_summary_json)
    summary: dict[str, Any] = {}
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))

    network_path = Path(paths.hydrographic_network_generated_shp)
    network_shp = str(network_path) if _vector_artifact_exists(network_path) else None
    network_gdf = None
    if network_shp is not None:
        network_gdf = gpd.read_file(network_shp)
    river_mesh_trace = (
        None
        if network_gdf is None
        else _build_river_mesh_trace_from_network_gdf(
            network_gdf=network_gdf,
            network_crs=crs_project,
        )
    )
    active_streams_tif = (
        paths.river_streams_pruned_tif
        if bool(config.river_network.prune_short_streams)
        else paths.river_streams_tif
    )
    return RiverNetworkProducts(
        enabled=True,
        threshold_cells=(
            None if summary.get("threshold_cells") is None else float(summary["threshold_cells"])
        ),
        flow_acc_cells_tif=str(Path(paths.correcflow_path) / "dem_acc_cells.tif"),
        streams_tif=paths.river_streams_tif,
        active_streams_tif=active_streams_tif,
        streams_pruned_tif=(
            paths.river_streams_pruned_tif
            if bool(config.river_network.prune_short_streams)
            else None
        ),
        stream_order_strahler_tif=(
            paths.river_stream_order_strahler_tif
            if bool(config.river_network.compute_strahler_order)
            else None
        ),
        stream_link_id_tif=(
            paths.river_stream_link_id_tif
            if bool(config.river_network.compute_stream_links)
            else None
        ),
        network_shp=network_shp,
        network_crs=crs_project,
        river_mesh_trace=river_mesh_trace,
        summary_json=paths.hydrographic_network_generated_summary_json,
    )


def _required_geographic_cache_artifacts(
    *,
    config: GeographicConfig,
    paths: GeographicPaths,
    flow_products: FlowProducts,
    raster_products: DomainRasterProducts,
) -> list[str | Path]:
    """Return the concrete files required for a safe cache hit."""
    required: list[str | Path] = [
        flow_products.correc,
        flow_products.direc,
        flow_products.acc,
        paths.watershed,
        paths.watershed_shp,
        paths.watershed_contour_shp,
        Path(paths.geographic_path) / "watershed_buff.shp",
        paths.watershed_box_shp,
        paths.box_buff,
        raster_products.watershed_box_buff_dem,
        raster_products.watershed_box_buff_fill,
        raster_products.watershed_box_buff_direc,
        raster_products.watershed_buff_dem,
        raster_products.watershed_buff_fill,
        raster_products.watershed_buff_direc,
        raster_products.watershed_dem,
        raster_products.watershed_fill,
        raster_products.watershed_direc,
        raster_products.watershed_contour_tif,
    ]
    if bool(config.river_network.enabled):
        required.extend(
            [
                Path(paths.correcflow_path) / "dem_acc_cells.tif",
                paths.river_streams_tif,
                paths.hydrographic_network_generated_summary_json,
            ]
        )
        if bool(config.river_network.prune_short_streams):
            required.append(paths.river_streams_pruned_tif)
        if bool(config.river_network.compute_strahler_order):
            required.append(paths.river_stream_order_strahler_tif)
        if bool(config.river_network.compute_stream_links):
            required.append(paths.river_stream_link_id_tif)
    return required


def _load_cached_geographic_products(
    *,
    config: GeographicConfig,
    paths: GeographicPaths,
    crs_project: str | None,
) -> _CachedGeographicProducts | None:
    """Return cached products when enabled, fingerprinted, and complete."""
    if not bool(config.reuse_existing_outputs):
        return None
    manifest_path = _geographic_cache_manifest_path(paths)
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if manifest.get("schema") != _GEOGRAPHIC_CACHE_SCHEMA_VERSION:
        return None
    if manifest.get("fingerprint") != _geographic_cache_fingerprint(config):
        return None

    flow_products = _flow_products_from_paths(paths, str(config.dem_correc_type))
    raster_products = _raster_products_from_paths(paths)
    required = _required_geographic_cache_artifacts(
        config=config,
        paths=paths,
        flow_products=flow_products,
        raster_products=raster_products,
    )
    if not _all_artifacts_exist(required):
        return None

    river_network_products = _river_products_from_cache(
        config=config,
        paths=paths,
        crs_project=crs_project,
    )
    if bool(config.river_network.enabled):
        summary_path = Path(paths.hydrographic_network_generated_summary_json)
        if summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            if (
                int(summary.get("segment_count", 0) or 0) > 0
                and river_network_products.network_shp is None
            ):
                return None

    catchment_area_km2 = float(manifest["catchment_area_km2"])
    domain_products = CatchmentDomainProducts(
        catchment_area_km2=catchment_area_km2,
        buffer_distance_m=float(manifest["buffer_distance_m"]),
        watershed_buff_shp=str(Path(paths.geographic_path) / "watershed_buff.shp"),
        watershed_box_shp=paths.watershed_box_shp,
        watershed_box_buff_shp=paths.box_buff,
    )
    return _CachedGeographicProducts(
        flow_products=flow_products,
        domain_products=domain_products,
        raster_products=raster_products,
        river_network_products=river_network_products,
        catchment_area_km2=catchment_area_km2,
    )


def _write_geographic_cache_manifest(
    *,
    config: GeographicConfig,
    paths: GeographicPaths,
    domain_products: CatchmentDomainProducts,
    catchment_area_km2: float,
) -> None:
    """Persist one cache manifest after a successful geographic build."""
    if not bool(config.reuse_existing_outputs):
        return
    manifest = {
        "schema": _GEOGRAPHIC_CACHE_SCHEMA_VERSION,
        "fingerprint": _geographic_cache_fingerprint(config),
        "catchment_area_km2": float(catchment_area_km2),
        "buffer_distance_m": float(domain_products.buffer_distance_m),
    }
    manifest_path = _geographic_cache_manifest_path(paths)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_geographic_runtime_context(
    *,
    config: GeographicConfig,
    out_dir_path: str | Path,
    backend: object | None = None,
    locator_factory: object = Nominatim,
) -> GeographicRuntimeContext:
    """Build the full geographic runtime context from config and workspace.

    This is the compatibility-oriented counterpart to
    ``build_domain_geographic_context``.

    The function prepares regional flow rasters, standard or direct DEM domain
    polygons, clipped domain rasters, DEM metadata, and optional river-network
    products. When cache reuse is enabled, it validates the cache fingerprint
    and reconstructs the same context from existing artifacts.
    """
    setup = prepare_geographic_run(
        config=config,
        out_dir_path=out_dir_path,
    )

    tool = resolve_delineation_backend(backend)
    cached_products = _load_cached_geographic_products(
        config=config,
        paths=setup.paths,
        crs_project=setup.crs_project,
    )

    if cached_products is not None:
        flow_products = cached_products.flow_products
        domain_products = cached_products.domain_products
        raster_products = cached_products.raster_products
        river_network_products = cached_products.river_network_products
        catchment_area_km2 = cached_products.catchment_area_km2
    else:
        flow_products = build_regional_flow_products(
            dem_init_path=setup.dem_init_path,
            dem_out_dir_path=setup.paths.correcflow_path,
            dem_correc_type=str(config.dem_correc_type),
            crs_project=setup.crs_project,
            backend=tool,
        )

        if config.catch_def == "dem":
            dem_products = build_direct_dem_domain(
                dem_init_path=setup.dem_init_path,
                paths=setup.paths,
                crs_project=setup.crs_project,
            )
            catchment_area_km2 = float(dem_products.domain_area_km2)
            domain_products = CatchmentDomainProducts(
                catchment_area_km2=catchment_area_km2,
                buffer_distance_m=0.0,
                watershed_buff_shp=dem_products.watershed_buff_shp,
                watershed_box_shp=dem_products.watershed_box_shp,
                watershed_box_buff_shp=dem_products.watershed_box_buff_shp,
            )
        else:
            build_standard_catchment(
                config=config,
                paths=setup.paths,
                direc_path=flow_products.direc,
                acc_path=flow_products.acc,
                direc_data=flow_products.direc_data,
                acc_data=flow_products.acc_data,
                crs_project=setup.crs_project,
                backend=tool,
                unsupported_mode="ignore",
            )
            catchment_area_km2 = float(compute_catchment_area_km2(setup.paths.watershed_shp))
            domain_products = build_standard_domain_polygons(
                config=config,
                paths=setup.paths,
                dem_init_path=setup.dem_init_path,
                crs_project=setup.crs_project,
            )

        tool.delineation.polygons_to_lines(
            setup.paths.watershed_shp,
            setup.paths.watershed_contour_shp,
        )

        river_network_products = build_river_network_products(
            river_network=config.river_network,
            dem_correc_path=flow_products.correc,
            d8_pointer_path=flow_products.direc,
            watershed_shp=setup.paths.watershed_shp,
            geographic_dir=setup.paths.geographic_path,
            correcflow_dir=setup.paths.correcflow_path,
            dem_res_m=float(setup.dem_res),
            streams_tif_path=setup.paths.river_streams_tif,
            streams_pruned_tif_path=setup.paths.river_streams_pruned_tif,
            stream_order_strahler_tif_path=setup.paths.river_stream_order_strahler_tif,
            stream_link_id_tif_path=setup.paths.river_stream_link_id_tif,
            network_shp_path=setup.paths.hydrographic_network_generated_shp,
            summary_json_path=setup.paths.hydrographic_network_generated_summary_json,
            network_crs=setup.crs_project,
            backend=tool,
        )

        raster_products = build_domain_rasters(
            dem_init_path=setup.dem_init_path,
            correc_path=flow_products.correc,
            direc_path=flow_products.direc,
            correc_data=flow_products.correc_data,
            direc_data=flow_products.direc_data,
            watershed_shp=setup.paths.watershed_shp,
            watershed_buff_shp=domain_products.watershed_buff_shp,
            paths=setup.paths,
            crs_project=setup.crs_project,
            backend=tool,
        )
        _write_geographic_cache_manifest(
            config=config,
            paths=setup.paths,
            domain_products=domain_products,
            catchment_area_km2=catchment_area_km2,
        )

    dem_metadata = read_dem_metadata(
        watershed_box_buff_dem_path=raster_products.watershed_box_buff_dem,
        watershed_buff_dem_path=raster_products.watershed_buff_dem,
        watershed_dem_path=raster_products.watershed_dem,
        crs_project=setup.crs_project,
        locator_factory=locator_factory,
    )

    return GeographicRuntimeContext(
        paths=setup.paths,
        flow_products=flow_products,
        raster_products=raster_products,
        dem_metadata=dem_metadata,
        river_network_products=river_network_products,
        catchment_area_km2=catchment_area_km2,
        crs_project=setup.crs_project,
        epsg=setup.epsg,
        dem_res=setup.dem_res,
    )
