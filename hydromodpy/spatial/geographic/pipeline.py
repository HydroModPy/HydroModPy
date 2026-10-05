"""Assemble the full geographic artifact set from one config + workspace.

Builds the runtime payload consumed by ``CatchmentDelineation``.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import geopandas as gpd
from geopy.geocoders import Nominatim
from rasterio.errors import RasterioIOError

from hydromodpy.core import progress
from hydromodpy.core.exceptions import TerrainProductError
from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.geographic.artifacts import DESCRIPTION_FILENAME
from hydromodpy.spatial.geographic.core.bed_regularization_raster import (
    bed_dem_path,
    bed_regularization_enabled,
    ground_bed_path,
    ground_bed_report_path,
    regularized_ground_from_config,
    top_dem_path_from_config,
)
from hydromodpy.spatial.geographic.core.catchment_domain import CatchmentDomainProducts
from hydromodpy.spatial.geographic.core.catchment_metrics import compute_catchment_area_km2
from hydromodpy.spatial.geographic.core.direct_dem_domain import build_direct_dem_domain
from hydromodpy.spatial.geographic.core.flow_products import (
    ACCUMULATION_NAME,
    DIRECTION_NAME,
    FlowProducts,
    build_regional_flow_products,
    capped_breach_of,
    corrected_dem_name,
    flow_products_from_paths,
)
from hydromodpy.spatial.geographic.core.ground_corrections import (
    close_notch_report,
    first_pass_channel,
    ground_dem_from_config,
    ground_dem_path_from_config,
    notch_enabled,
    notch_lowered_pixels,
)
from hydromodpy.spatial.geographic.core.lake_enforcement import (
    capture_from_config,
    routing_dem_from_config,
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
from hydromodpy.spatial.geographic.core.stream_dem_agreement import (
    report_network_dem_agreement,
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
from hydromodpy.spatial.geographic.regional_flow_copy import copy_regional_flow_from_job
from hydromodpy.spatial.terrain import CappedBreachReport

logger = get_logger(__name__)

# v2 carries the outlet the delineation actually ran from, which v1 lost: a
# context rebuilt from a v1 description reported the declared outlet as if
# nothing had been snapped.
_GEOGRAPHIC_CACHE_SCHEMA_VERSION = "hydromodpy_geographic_cache_v2"

# Relative catchment-area change above which the stream-capture re-delineation is
# reported as a moved divide rather than a connected channel.
_CAPTURE_AREA_DRIFT_TOL = 0.05

# The clips of the ground the model top is sampled from, one per domain_extent.
_TOP_CLIP_ATTRIBUTES = ("watershed_box_buff_dem", "watershed_buff_dem", "watershed_dem")

# The other rasters build_domain_rasters writes. Clipping the regularised ground
# writes them to a scratch folder: they are the clips of the flow products,
# already written next to the clips of G.
_FLOW_CLIP_ATTRIBUTES = (
    "watershed_box_buff_fill",
    "watershed_box_buff_direc",
    "watershed_buff_fill",
    "watershed_buff_direc",
    "watershed_fill",
    "watershed_direc",
    "watershed_contour_tif",
)


@dataclass(frozen=True)
class _CachedGeographicProducts:
    """Artifact views reconstructed from one validated geographic cache hit."""

    flow_products: FlowProducts
    domain_products: CatchmentDomainProducts
    raster_products: DomainRasterProducts
    river_network_products: RiverNetworkProducts
    catchment_area_km2: float
    x_outlet_snapped: float | None = None
    y_outlet_snapped: float | None = None
    outlet_snap_distance_m: float | None = None


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
    top_dem_path: str
    crs_project: str | None
    epsg: int | None
    dem_res: float
    x_outlet: float | None = None
    y_outlet: float | None = None
    x_outlet_snapped: float | None = None
    """Outlet the delineation actually ran from. x_outlet is what the config declared."""

    y_outlet_snapped: float | None = None
    outlet_snap_distance_m: float | None = None
    buffer_distance_m: float | None = None
    """Margin drawn around the catchment, in metres, after rounding to the DEM."""

    buffer_area_increase: float | None = None
    """Relative area the margin added to the catchment; None when not recorded."""

    top_surface_paths: dict[str, str] = field(default_factory=dict)
    """Clips the model top is sampled from, by attribute, where they are not the clips of G.

    Filled by ``[geographic.bed_regularization]`` with the clips of the
    regularised ground, cut by the routine and the polygons that cut the clips
    of G. They replace the clips of G under the same attribute names, and
    ``top_dem_path`` is the regularised ground itself, so the model top and
    the SFR bed read one bed. The routing DEM, the channel tree, the catchment
    and the mesh are built before and do not read them.
    """

    def runtime_attributes(self) -> dict[str, object]:
        """Return the public attribute payload expected from ``CatchmentDelineation``."""
        attrs = dict(vars(self.paths))
        attrs.update(self.top_surface_paths)
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
                "x_outlet": self.x_outlet,
                "y_outlet": self.y_outlet,
                "x_outlet_snapped": self.x_outlet_snapped,
                "y_outlet_snapped": self.y_outlet_snapped,
                "outlet_snap_distance_m": self.outlet_snap_distance_m,
                "buffer_distance_m": self.buffer_distance_m,
                "buffer_area_increase": self.buffer_area_increase,
                "_paths": self.paths,
                "_dem_metadata": self.dem_metadata,
                "_river_network_products": self.river_network_products,
                "_flow_products": self.flow_products,
                "_top_dem_path": self.top_dem_path,
            }
        )
        attrs.update(self.dem_metadata.runtime_attributes())
        return attrs


def _geographic_cache_manifest_path(paths: GeographicPaths) -> Path:
    """Return the cache manifest path for one geographic workspace."""
    return Path(paths.geographic_path) / DESCRIPTION_FILENAME


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
    # The limits exist only for the method that reads them. Left out when unset,
    # a fill or breach config fingerprints as it did before the capped breach
    # existed, so the trees already cached stay valid.
    if config_payload.get("capped_breach") is None:
        config_payload.pop("capped_breach", None)
    # Same rule for the notch: off, it changes nothing, so it leaves a cached
    # tree valid. Its vector is signed below when it is on.
    # The bed regularisation reads the weirs and dams of the crossings file, so
    # the section stays signed while either reads it.
    if not config.crossings.enabled and not config.bed_regularization.enabled:
        config_payload.pop("crossings", None)
    # Same rule for the bed regularisation: off, it changes nothing.
    if not config.bed_regularization.enabled:
        config_payload.pop("bed_regularization", None)
    payload = {
        "schema": _GEOGRAPHIC_CACHE_SCHEMA_VERSION,
        "config": config_payload,
        "inputs": {
            "dem_init_path": _path_signature(config.dem_init_path),
            "polyg_shp_path": _path_signature(config.polyg_shp_path),
            # The vectors that condition the routing DEM and the model
            # top. Editing one in place changes every product below without
            # changing a single config value, so the config payload alone
            # cannot see it.
            "lake_geometry_path": _path_signature(config.enforce_lakes.lake_geometry_path),
            "dam_carve_line_path": _path_signature(config.dam_carve.line_path),
        },
    }
    if config.crossings.enabled or config.bed_regularization.enabled:
        payload["inputs"]["crossings_path"] = _path_signature(config.crossings.path)
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


def _flow_raster_paths(paths: GeographicPaths, dem_correc_type: str) -> list[str | Path]:
    """Return the three regional rasters one conditioning method writes."""
    correcflow = Path(paths.correcflow_path)
    return [
        correcflow / corrected_dem_name(dem_correc_type),
        correcflow / DIRECTION_NAME,
        correcflow / ACCUMULATION_NAME,
    ]


def _raster_products_from_paths(paths: GeographicPaths) -> DomainRasterProducts:
    """Reconstruct the raster-products view from canonical cache paths."""
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
    generated_network_shp = str(network_path) if _vector_artifact_exists(network_path) else None
    network_gdf = None
    if generated_network_shp is not None:
        network_gdf = gpd.read_file(generated_network_shp)
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
        hydrographic_network_generated_shp=generated_network_shp,
        network_crs=crs_project,
        river_mesh_trace=river_mesh_trace,
        hydrographic_network_generated_summary_json=(
            paths.hydrographic_network_generated_summary_json
        ),
        stream_order_strahler_full_tif=(
            str(Path(paths.correcflow_path) / "dem_stream_order_strahler_full.tif")
            if bool(config.river_network.compute_strahler_order)
            else None
        ),
        stream_link_id_full_tif=(
            str(Path(paths.correcflow_path) / "dem_stream_link_id_full.tif")
            if bool(config.river_network.compute_stream_links)
            else None
        ),
    )


def _required_geographic_cache_artifacts(
    *,
    config: GeographicConfig,
    paths: GeographicPaths,
    raster_products: DomainRasterProducts,
) -> list[str | Path]:
    """Return the concrete files required for a safe cache hit."""
    required: list[str | Path] = [
        *_flow_raster_paths(paths, str(config.dem_correc_type)),
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
    required.extend(_top_surface_paths(config, paths).values())
    if bed_regularization_enabled(config):
        setup = SimpleNamespace(paths=paths)
        required.extend([ground_bed_path(setup), ground_bed_report_path(setup)])
    return required


def _top_surface_paths(config: GeographicConfig, paths: GeographicPaths) -> dict[str, str]:
    """The regularised copies of the model-top clips, empty when the bed is not regularised."""
    if not bed_regularization_enabled(config):
        return {}
    return {name: str(bed_dem_path(getattr(paths, name))) for name in _TOP_CLIP_ATTRIBUTES}


def _clip_regularised_ground(
    *,
    config: GeographicConfig,
    setup: Any,
    flow_products: FlowProducts,
    river_network_products: RiverNetworkProducts,
    domain_products: CatchmentDomainProducts,
    tool: object,
) -> None:
    """Fit the bed on the ground and clip the result as the ground was clipped.

    The same routine and the same polygons as the clips of G, so both carry
    the same georeference; only the output names differ (``_bed``).
    """
    bed = regularized_ground_from_config(
        config,
        setup,
        d8_tif=flow_products.direc,
        river_products=river_network_products,
    )
    paths = setup.paths
    with tempfile.TemporaryDirectory(dir=paths.correcflow_path) as scratch:
        bed_paths = replace(
            paths,
            **_top_surface_paths(config, paths),
            **{
                name: str(Path(scratch) / Path(getattr(paths, name)).name)
                for name in _FLOW_CLIP_ATTRIBUTES
            },
        )
        build_domain_rasters(
            dem_init_path=bed,
            correc_path=flow_products.correc,
            direc_path=flow_products.direc,
            watershed_shp=paths.watershed_shp,
            watershed_buff_shp=domain_products.watershed_buff_shp,
            paths=bed_paths,
            crs_project=setup.crs_project,
            backend=tool,
        )


def _load_cached_geographic_products(
    *,
    config: GeographicConfig,
    paths: GeographicPaths,
    crs_project: str | None,
    reuse_existing_outputs: bool | None = None,
) -> _CachedGeographicProducts | None:
    """Return cached products when enabled, fingerprinted, and complete.

    ``reuse_existing_outputs`` overrides the config flag when it is not None.
    A pipeline rebuilding a step it already completed passes True: that flag is
    a preference about what a *fresh* run does with a tree another run left,
    and a resume re-delineating its own products is a defect, not a preference.
    """
    reuse = (
        bool(config.reuse_existing_outputs)
        if reuse_existing_outputs is None
        else bool(reuse_existing_outputs)
    )
    if not reuse:
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

    raster_products = _raster_products_from_paths(paths)
    required = _required_geographic_cache_artifacts(
        config=config,
        paths=paths,
        raster_products=raster_products,
    )
    if not _all_artifacts_exist(required):
        return None
    # The model top is read from the ground. A tree written before the ground had
    # its own file lacks it and is rebuilt.
    ground = ground_dem_path_from_config(
        config, SimpleNamespace(dem_init_path=str(config.dem_init_path), paths=paths)
    )
    if not Path(ground).exists():
        return None

    # Only now: the description reads the CRS and the nodata off the rasters,
    # which have just been shown to exist. Existing is not enough -- a raster
    # left by an interrupted run, or written by another tool without a nodata
    # tag, cannot be described. A cache that cannot describe itself is a miss,
    # never a crash: the run rebuilds, which is what it would have done anyway.
    stored_report = manifest.get("conditioning_report")
    breach_report = (
        CappedBreachReport.from_document(stored_report) if stored_report is not None else None
    )
    try:
        flow_products = flow_products_from_paths(
            dem_out_dir_path=paths.correcflow_path,
            dem_correc_type=str(config.dem_correc_type),
            capped_breach=capped_breach_of(config),
            breach_report=breach_report,
        )
    except (TerrainProductError, RasterioIOError) as exc:
        logger.warning(
            "Geographic cache rejected: the flow rasters under %s exist but cannot be "
            "described (%s). Rebuilding them.",
            paths.correcflow_path,
            exc,
        )
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
                and river_network_products.hydrographic_network_generated_shp is None
            ):
                return None

    if breach_report is not None:
        logger.info(
            "Geographic cache hit, capped breach as built: %d cells lowered, %d cells "
            "raised; realised max lowering %.3f m for max_cost %.3f m.",
            breach_report.cells_lowered,
            breach_report.cells_raised,
            breach_report.max_lowering_m,
            breach_report.max_cost_m,
        )

    catchment_area_km2 = float(manifest["catchment_area_km2"])
    domain_products = CatchmentDomainProducts(
        catchment_area_km2=catchment_area_km2,
        buffer_distance_m=float(manifest["buffer_distance_m"]),
        watershed_buff_shp=str(Path(paths.geographic_path) / "watershed_buff.shp"),
        watershed_box_shp=paths.watershed_box_shp,
        watershed_box_buff_shp=paths.box_buff,
        # A manifest written before the buffer rules were recorded has none of
        # these three, and the products then say so with None.
        buffer_rule=manifest.get("buffer_rule"),
        buffer_declared=manifest.get("buffer_declared"),
        buffer_area_increase=_optional_float(manifest.get("buffer_area_increase")),
    )
    return _CachedGeographicProducts(
        flow_products=flow_products,
        domain_products=domain_products,
        raster_products=raster_products,
        river_network_products=river_network_products,
        catchment_area_km2=catchment_area_km2,
        x_outlet_snapped=_optional_float(manifest.get("x_outlet_snapped")),
        y_outlet_snapped=_optional_float(manifest.get("y_outlet_snapped")),
        outlet_snap_distance_m=_optional_float(manifest.get("outlet_snap_distance_m")),
    )


def _optional_float(value: object) -> float | None:
    """Return ``value`` as a float, or None when the description omits it."""
    return None if value is None else float(str(value))


def _write_geographic_cache_manifest(
    *,
    config: GeographicConfig,
    paths: GeographicPaths,
    domain_products: CatchmentDomainProducts,
    catchment_area_km2: float,
    catchment_products: object | None,
    flow_products: FlowProducts | None = None,
) -> None:
    """Describe the geographic tree just written, next to the tree itself.

    Written whatever ``reuse_existing_outputs`` says. That flag decides whether
    a fresh run reuses a tree some other run left; it says nothing about
    whether the products describe themselves. A tree without this document is
    a tree no later process - a resume, a reader, another run - can tell apart
    from the leftovers of an interrupted build.
    """
    manifest = {
        "schema": _GEOGRAPHIC_CACHE_SCHEMA_VERSION,
        "fingerprint": _geographic_cache_fingerprint(config),
        "catchment_area_km2": float(catchment_area_km2),
        "buffer_distance_m": float(domain_products.buffer_distance_m),
        "buffer_rule": domain_products.buffer_rule,
        "buffer_declared": domain_products.buffer_declared,
        "buffer_area_increase": domain_products.buffer_area_increase,
        "x_outlet_snapped": getattr(catchment_products, "x_outlet_snapped", None),
        "y_outlet_snapped": getattr(catchment_products, "y_outlet_snapped", None),
        "outlet_snap_distance_m": getattr(catchment_products, "snap_distance_m", None),
    }
    # What a capped breach dug, measured on the DEM before and after. Outside the
    # fingerprint: it is an output, and a cache hit logs it back from here.
    breach_report = (
        flow_products.accumulation.directions.conditioned_dem.breach_report
        if flow_products is not None
        else None
    )
    if breach_report is not None:
        manifest["conditioning_report"] = breach_report.to_document()
    manifest_path = _geographic_cache_manifest_path(paths)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _redelineate(
    *,
    config: GeographicConfig,
    setup: object,
    tool: object,
    routing_dem_path: str | Path,
) -> tuple[FlowProducts, float, CatchmentDomainProducts, RiverNetworkProducts]:
    """Condition, delineate, buffer and extract the network again on one routing DEM.

    The second pass of the crossing notch and of the lake capture: same steps as
    the first, on a routing DEM that was corrected after it.
    """
    flow_products = build_regional_flow_products(
        dem_init_path=routing_dem_path,
        dem_out_dir_path=setup.paths.correcflow_path,
        dem_correc_type=str(config.dem_correc_type),
        capped_breach=capped_breach_of(config),
        crs_project=setup.crs_project,
        backend=tool,
        engine_id=config.terrain_engine,
    )
    build_standard_catchment(
        config=config,
        paths=setup.paths,
        accumulation=flow_products.accumulation,
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
    return flow_products, catchment_area_km2, domain_products, river_network_products


def build_geographic_runtime_context(
    *,
    config: GeographicConfig,
    out_dir_path: str | Path,
    backend: object | None = None,
    locator_factory: object = Nominatim,
    reuse_existing_outputs: bool | None = None,
    network_map_path: str | Path | None = None,
) -> GeographicRuntimeContext:
    """Build the full geographic runtime context from config and workspace.

    This is the full runtime counterpart to
    ``build_geographic_derived_features``.

    The function prepares regional flow rasters, standard or direct DEM domain
    polygons, clipped domain rasters, DEM metadata, and optional river-network
    products. When cache reuse is enabled, it validates the cache fingerprint
    and reconstructs the same context from existing artifacts.

    ``network_map_path`` is the local vector file of the mapped network, when
    one is declared. It feeds the alpha diagnostic only and never the model.
    """
    setup = prepare_geographic_run(
        config=config,
        out_dir_path=out_dir_path,
    )

    tool = resolve_delineation_backend(backend)
    # Only the outlet branch snaps; a cached run, a dem or a polygon domain has
    # no snap to report.
    catchment_products: object | None = None
    cached_products = _load_cached_geographic_products(
        config=config,
        paths=setup.paths,
        crs_project=setup.crs_project,
        reuse_existing_outputs=reuse_existing_outputs,
    )

    if cached_products is not None:
        flow_products = cached_products.flow_products
        domain_products = cached_products.domain_products
        raster_products = cached_products.raster_products
        river_network_products = cached_products.river_network_products
        catchment_area_km2 = cached_products.catchment_area_km2
    else:
        # The ground is the DEM plus the declared corrections (the dam carve here, the
        # crossing notch after the first delineation). The routing chain starts from it,
        # and so does the model top (clipped below), so neither surface sees a
        # structure the other does not.
        # Routing conditioning: carve the lakes so streams route INTO them and drain
        # to the outlet.
        ground = ground_dem_from_config(config, setup)
        routing_dem_path = routing_dem_from_config(config, setup, dem_in_path=ground)
        if config.reg_fold is None:
            flow_products = build_regional_flow_products(
                dem_init_path=routing_dem_path,
                dem_out_dir_path=setup.paths.correcflow_path,
                dem_correc_type=str(config.dem_correc_type),
                capped_breach=capped_breach_of(config),
                crs_project=setup.crs_project,
                backend=tool,
                engine_id=config.terrain_engine,
            )
        else:
            flow_products = copy_regional_flow_from_job(
                config=config,
                routing_dem_path=routing_dem_path,
                output_dir=setup.paths.correcflow_path,
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
            catchment_products = build_standard_catchment(
                config=config,
                paths=setup.paths,
                accumulation=flow_products.accumulation,
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

        with progress.status("Extracting river network"):
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

        # Crossing notch: the channel tree of the first delineation says where the
        # embankments cross it. The ground is notched there and the catchment is
        # delineated again on it, before the lake capture reads its own channel.
        if notch_enabled(config):
            channel = first_pass_channel(
                config,
                setup,
                flow=flow_products,
                river_products=river_network_products,
                catchment_area_km2=catchment_area_km2,
            )
            ground = ground_dem_from_config(config, setup, channel=channel)
            if notch_lowered_pixels(setup) > 0:
                routing_dem_path = routing_dem_from_config(config, setup, dem_in_path=ground)
                with progress.status("Re-delineating on the notched ground"):
                    (
                        flow_products,
                        catchment_area_km2,
                        domain_products,
                        river_network_products,
                    ) = _redelineate(
                        config=config,
                        setup=setup,
                        tool=tool,
                        routing_dem_path=routing_dem_path,
                    )
            close_notch_report(setup, catchment_area_km2_after=catchment_area_km2)

        # Second enforcement pass: carve any stream that dead-ends near a lake (a flat
        # forebay near-miss) to the shoreline and re-delineate, so its channel reaches
        # the lake instead of leaving unfed. Standard-catchment branch only.
        captured_dem = capture_from_config(
            config,
            setup,
            flow_direc=flow_products.direc,
            link_id_tif=getattr(river_network_products, "stream_link_id_full_tif", None),
            dem_in_path=routing_dem_path,
        )
        if captured_dem is not None and config.catch_def != "dem":
            with progress.status("Re-delineating on captured streams"):
                area_before_capture = catchment_area_km2
                (
                    flow_products,
                    catchment_area_km2,
                    domain_products,
                    river_network_products,
                ) = _redelineate(
                    config=config,
                    setup=setup,
                    tool=tool,
                    routing_dem_path=captured_dem,
                )
                # Capture must CONNECT a stream to the lake, never redraw the divide. A
                # carved channel is a new low path: if it breaches the watershed boundary,
                # the second delineation annexes the neighbouring basin and the model stops
                # being the catchment that was asked for: a single carved channel of a
                # few dozen cells is enough to more than double the area. Loud, because
                # nothing downstream can tell the difference.
                if area_before_capture > 0.0:
                    drift = abs(catchment_area_km2 - area_before_capture) / area_before_capture
                    if drift > _CAPTURE_AREA_DRIFT_TOL:
                        logger.warning(
                            "stream capture moved the watershed divide: the catchment went "
                            "from %.2f to %.2f km2 (%+.0f %%) after re-delineating on the "
                            "carved DEM. The carved channel most likely breached the divide "
                            "and annexed a neighbouring basin, so the model no longer covers "
                            "the requested catchment. Lower "
                            "geographic.enforce_lakes.capture_radius_m, reduce buffer_m, or "
                            "drop the capture pass and raise "
                            "flow.sinks_sources.sfr.<id>.lake_feeder_snap instead.",
                            area_before_capture,
                            catchment_area_km2,
                            100.0 * (catchment_area_km2 / area_before_capture - 1.0),
                        )

        with progress.status("Clipping domain rasters"):
            # The model TOP is clipped from the ground: the DEM with the dam carved and
            # the crossings notched, as the routing above saw it.
            raster_products = build_domain_rasters(
                dem_init_path=ground_dem_path_from_config(config, setup),
                correc_path=flow_products.correc,
                direc_path=flow_products.direc,
                watershed_shp=setup.paths.watershed_shp,
                watershed_buff_shp=domain_products.watershed_buff_shp,
                paths=setup.paths,
                crs_project=setup.crs_project,
                backend=tool,
            )
        # The channel bed of the ground, regularised on the channel tree A once A
        # and the catchment are final. Nothing above reads it.
        if bed_regularization_enabled(config):
            with progress.status("Regularising the channel bed of the ground"):
                _clip_regularised_ground(
                    config=config,
                    setup=setup,
                    flow_products=flow_products,
                    river_network_products=river_network_products,
                    domain_products=domain_products,
                    tool=tool,
                )
        _write_geographic_cache_manifest(
            config=config,
            paths=setup.paths,
            domain_products=domain_products,
            catchment_area_km2=catchment_area_km2,
            catchment_products=catchment_products,
            flow_products=flow_products,
        )

    # Alpha describes the current map, so it is measured on a cache hit too. The map
    # is not a model input and stays out of the cache fingerprint.
    if config.catch_def != "dem":
        report_network_dem_agreement(
            setup,
            network_map_path=network_map_path,
            d8_pointer_path=flow_products.direc,
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
        top_dem_path=top_dem_path_from_config(config, setup),
        crs_project=setup.crs_project,
        epsg=setup.epsg,
        dem_res=setup.dem_res,
        x_outlet=(float(config.x_outlet) if config.x_outlet is not None else None),
        y_outlet=(float(config.y_outlet) if config.y_outlet is not None else None),
        x_outlet_snapped=(
            cached_products.x_outlet_snapped
            if cached_products is not None
            else getattr(catchment_products, "x_outlet_snapped", None)
        ),
        y_outlet_snapped=(
            cached_products.y_outlet_snapped
            if cached_products is not None
            else getattr(catchment_products, "y_outlet_snapped", None)
        ),
        outlet_snap_distance_m=(
            cached_products.outlet_snap_distance_m
            if cached_products is not None
            else getattr(catchment_products, "snap_distance_m", None)
        ),
        buffer_distance_m=float(domain_products.buffer_distance_m),
        buffer_area_increase=domain_products.buffer_area_increase,
        top_surface_paths=_top_surface_paths(config, setup.paths),
    )
