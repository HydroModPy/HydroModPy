"""The cache of the geographic tree: what a runtime left on disk, its fingerprint and its manifest.

A run reuses the tree of an earlier run when the fingerprint of its inputs
matches the manifest written next to the tree and every file it names exists.

Both geographic runtimes - the delineated :class:`CatchmentDelineation` and the
synthetic one - hydrate the same public attribute names once they have run.
Asking the object rather than rebuilding paths from the config keeps the two on
one answer, and keeps the list honest: a path the runtime names but never wrote
is dropped, because a step declares what it left, not what it could have left.

The declaration covers **every file a rebuild of the step reads**, so a digest
over it changes exactly when what a resume would reuse changes. The files of the
tree are written once, in ``_TREE_FILES``, which the cache check of the pipeline
reads too (:func:`reused_tree_files`). Two of those files are named by no public
attribute and are derived from the two directory attributes that are.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import geopandas as gpd
from rasterio.errors import RasterioIOError

from hydromodpy.core.exceptions import TerrainProductError
from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.geographic.capped_breach_config import capped_breach_of
from hydromodpy.spatial.geographic.core.catchment_domain import CatchmentDomainProducts
from hydromodpy.spatial.geographic.core.flow_products import (
    ACCUMULATION_NAME,
    DIRECTION_NAME,
    FlowProducts,
    corrected_dem_name,
    flow_products_from_paths,
)
from hydromodpy.spatial.geographic.core.ground_bed import (
    bed_dem_path,
    bed_regularization_enabled,
    ground_bed_path,
    ground_bed_report_path,
    regularized_ground_from_config,
)
from hydromodpy.spatial.geographic.core.ground_corrections import ground_dem_path_from_config
from hydromodpy.spatial.geographic.core.river_mesh_trace import (
    build_river_mesh_trace_from_network_gdf,
)
from hydromodpy.spatial.geographic.core.river_network import RiverNetworkProducts
from hydromodpy.spatial.geographic.domain_rasters import DomainRasterProducts, build_domain_rasters
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.spatial.geographic.geographic_paths import GeographicPaths
from hydromodpy.spatial.terrain import CappedBreachReport

# Every file of a geographic tree. The first item locates the file: the
# attribute that names it on GeographicPaths and on the runtimes, or a directory
# attribute and a file name for the two files no attribute names. The second
# item says when a reuse of the tree needs the file: in every tree ("always"),
# with [geographic.river_network] on ("enabled"), with that table's option that
# writes it on as well, or never (None). A reuse checks the network vector
# through the summary's segment count, and ``watershed_buff_shp`` and
# ``box_buff_shp`` are other spellings of two files above that a runtime may
# set; the declaration still covers them when they exist.
_TREE_FILES: tuple[tuple[str | tuple[str, str], str | None], ...] = (
    ("watershed", "always"),
    ("watershed_shp", "always"),
    ("watershed_contour_shp", "always"),
    (("geographic_path", "watershed_buff.shp"), "always"),
    ("watershed_box_shp", "always"),
    ("box_buff", "always"),
    ("watershed_box_buff_dem", "always"),
    ("watershed_box_buff_fill", "always"),
    ("watershed_box_buff_direc", "always"),
    ("watershed_buff_dem", "always"),
    ("watershed_buff_fill", "always"),
    ("watershed_buff_direc", "always"),
    ("watershed_dem", "always"),
    ("watershed_fill", "always"),
    ("watershed_direc", "always"),
    ("watershed_contour_tif", "always"),
    (("correcflow_path", "dem_acc_cells.tif"), "enabled"),
    ("river_streams_tif", "enabled"),
    ("hydrographic_network_generated_summary_json", "enabled"),
    ("river_streams_pruned_tif", "prune_short_streams"),
    ("river_stream_order_strahler_tif", "compute_strahler_order"),
    ("river_stream_link_id_tif", "compute_stream_links"),
    ("hydrographic_network_generated_shp", None),
    ("watershed_buff_shp", None),
    ("box_buff_shp", None),
)

# Attributes of the regional flow-product view. These three rasters are the
# expensive half of a delineation and are what a resume must not recompute.
_FLOW_PRODUCT_ATTRIBUTES = ("correc", "direc", "acc")

# A shapefile is a file only by convention: reopening it needs its sidecars, so
# the declaration names them and a digest covers the whole vector. The flag
# marks the three a reuse needs to reopen the vector. The .prj and .cpg are
# digested when they exist and a reuse does not ask for them.
SHAPEFILE_SIDECARS = (
    (".shp", True),
    (".shx", True),
    (".dbf", True),
    (".prj", False),
    (".cpg", False),
)

DESCRIPTION_FILENAME = "_geographic_cache_manifest.json"


def _tree_file(owner: object, location: str | tuple[str, str]) -> str | Path | None:
    """Return the path one entry of ``_TREE_FILES`` names on *owner*, or None."""
    if isinstance(location, str):
        return getattr(owner, location, None)
    folder = getattr(owner, location[0], None)
    return Path(str(folder)) / location[1] if folder else None


def reused_tree_files(paths: object, river_network: Any) -> list[str | Path]:
    """Return the files of the tree under *paths* that a reuse needs, in table order.

    *river_network* is the ``[geographic.river_network]`` config the tree was
    built with.
    """
    network_on = bool(river_network.enabled)
    return [
        _tree_file(paths, location)
        for location, needed in _TREE_FILES
        if needed == "always"
        or (needed is not None and network_on and bool(getattr(river_network, needed)))
    ]


def _expand(raw: object) -> list[Path]:
    """Return the existing files one declared path stands for."""
    if raw in (None, ""):
        return []
    path = Path(str(raw))
    if path.suffix.lower() == ".shp":
        return [
            sidecar
            for suffix, _ in SHAPEFILE_SIDECARS
            if (sidecar := path.with_suffix(suffix)).is_file()
        ]
    return [path] if path.is_file() else []


def geographic_artifact_paths(geographic: object) -> tuple[Path, ...]:
    """Return every file a geographic runtime wrote and still holds.

    The description document comes first when it exists: it is what tells a
    later process that the tree beside it is complete and whose it is.
    """
    if geographic is None:
        return ()

    found: list[Path] = []
    geographic_path = getattr(geographic, "geographic_path", None)
    if geographic_path:
        found.extend(_expand(Path(str(geographic_path)) / DESCRIPTION_FILENAME))

    for location, _ in _TREE_FILES:
        found.extend(_expand(_tree_file(geographic, location)))

    flow_products = getattr(geographic, "_flow_products", None)
    for name in _FLOW_PRODUCT_ATTRIBUTES:
        found.extend(_expand(getattr(flow_products, name, None)))

    seen: dict[Path, None] = {}
    for path in found:
        seen.setdefault(path, None)
    return tuple(sorted(seen))


__all__ = (
    "DESCRIPTION_FILENAME",
    "SHAPEFILE_SIDECARS",
    "geographic_artifact_paths",
    "reused_tree_files",
)


logger = get_logger(__name__)

# v2 carries the outlet the delineation actually ran from, which v1 lost: a
# context rebuilt from a v1 description reported the declared outlet as if
# nothing had been snapped.
_GEOGRAPHIC_CACHE_SCHEMA_VERSION = "hydromodpy_geographic_cache_v2"

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
class GeographicProducts:
    """Artifact views of one geographic tree, built by the pipeline or read from a cache hit."""

    flow_products: FlowProducts
    domain_products: CatchmentDomainProducts
    raster_products: DomainRasterProducts
    river_network_products: RiverNetworkProducts
    catchment_area_km2: float
    x_outlet_snapped: float | None = None
    y_outlet_snapped: float | None = None
    outlet_snap_distance_m: float | None = None


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


def geographic_cache_fingerprint(config: GeographicConfig) -> str:
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
    # Same rule for the cell size: unset, the DEM keeps its pixel, as it did
    # before the key existed, so the trees already cached stay valid.
    catchment_payload = config_payload.get("catchment")
    if isinstance(catchment_payload, dict) and catchment_payload.get("dem_resolution") is None:
        catchment_payload.pop("dem_resolution", None)
    # Same rule for the snap method: the window snap is what every tree cached
    # before the key existed was built with.
    if isinstance(catchment_payload, dict) and catchment_payload.get("snap_method") == "window":
        catchment_payload.pop("snap_method", None)
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
    return all(
        vector_path.with_suffix(suffix).exists() for suffix, needed in SHAPEFILE_SIDECARS if needed
    )


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
        else build_river_mesh_trace_from_network_gdf(
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


def required_geographic_cache_artifacts(
    *,
    config: GeographicConfig,
    paths: GeographicPaths,
) -> list[str | Path]:
    """Return the concrete files required for a safe cache hit."""
    required: list[str | Path] = [
        *_flow_raster_paths(paths, str(config.dem_correc_type)),
        *reused_tree_files(paths, config.river_network),
    ]
    required.extend(resolve_top_surface_paths(config, paths).values())
    if bed_regularization_enabled(config):
        setup = SimpleNamespace(paths=paths)
        required.extend([ground_bed_path(setup), ground_bed_report_path(setup)])
    return required


def resolve_top_surface_paths(config: GeographicConfig, paths: GeographicPaths) -> dict[str, str]:
    """The regularised copies of the model-top clips, empty when the bed is not regularised."""
    if not bed_regularization_enabled(config):
        return {}
    return {name: str(bed_dem_path(getattr(paths, name))) for name in _TOP_CLIP_ATTRIBUTES}


def clip_regularised_ground(
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
            **resolve_top_surface_paths(config, paths),
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


def load_cached_geographic_products(
    *,
    config: GeographicConfig,
    paths: GeographicPaths,
    crs_project: str | None,
    reuse_existing_outputs: bool | None = None,
) -> GeographicProducts | None:
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
    if manifest.get("fingerprint") != geographic_cache_fingerprint(config):
        return None

    raster_products = _raster_products_from_paths(paths)
    required = required_geographic_cache_artifacts(config=config, paths=paths)
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
    return GeographicProducts(
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


def write_geographic_cache_manifest(
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
        "fingerprint": geographic_cache_fingerprint(config),
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
