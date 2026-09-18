"""Bridge between ``[[data.hydrography.sources]]`` and the network the burn reads.

Twin of :mod:`~hydromodpy.data.variables.dem.resolver`, on the linework instead
of the elevation. The stream burn runs inside the geographic step, before any
data manager, so it cannot read what ``LoadDataStep`` later produces: it needs a
concrete file on disk. Users therefore had to declare the same network twice,
once under ``[[data.hydrography.sources]]`` for the data layer and once under
``geographic.enforce_streams.stream_geometry_path`` for the burn. This resolver
removes that duplication by filling the geographic field from the data
declaration when the geographic one is left empty.

Resolution order for a single source:

- ``source = "custom"`` resolves ``path`` against the TOML directory, picking the
  first vector file when it points at a directory. A raster is skipped: the burn
  rasterizes geometries onto the DEM grid itself and has nothing to do with an
  already gridded network.
- any other source is a registered one, and it downloads on a bootstrap bbox
  built around the outlet, because the watershed the data manager clips against
  does not exist yet at this point in the pipeline. That regional extent is what
  the burn wants anyway: the trench is cut into the regional routing DEM, before
  delineation. The three names this module used to carry are gone: the section
  says ``custom`` or it says a name the source registry resolves, and a name
  nobody serves is refused there, listing what this installation does serve.

The bootstrap download is cached on disk under its own name and deliberately not
registered in the data catalog, so the data manager fetches the same source once
more on its own watershed box. Reaching the catalog from here would be legal and
safe (``data -> data``, and concurrent opens on one cache.duckdb are covered by
``tests/unit/results/test_db_retry.py``), but registering costs more than the one
fetch it saves:

- ``register`` goes through ``reject_frozen_register``, and frozen mode is armed
  before the pipeline runs, so a ``--frozen`` replay would then demand this
  regional file in ``hydromodpy.lock`` with a matching sha256.
- ``subsume_entries`` deletes the entries CONTAINED in the bbox it is given, and
  unlinks their files. The manager passes its watershed bbox, so a bootstrap row
  either survives forever as an orphan, or, on a catchment wider than the
  bootstrap box, gets its file unlinked and re-downloaded at the next run.
- ``find_cached`` matches on a superset bbox, so the saving only ever applies to
  a catchment that fits inside the bootstrap box. It is absent from exactly the
  large catchments where the subsume above bites.

The waste is one request, on the first run of a project only: afterwards the
outlet box recomputes identically and ``out_path`` already exists.

The first source that yields a usable path wins.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import cache_dir as _hmp_cache_dir

logger = get_logger(__name__)

_BOOTSTRAP_BUFFER_M = 30_000
"""Half-width of the outlet box the API sources are fetched on, in metres.

Same value as the DEM bootstrap, and for the same reason: the watershed is not
delineated yet, so the only extent available is a box around the declared
outlet. It is intersected with the DEM footprint when one is known, since a
reach outside the DEM cannot be burned into it.
"""


def resolve_stream_geometry_path_from_data_sources(
    cfg: Any,
    *,
    config_path: Path,
    cache_dir: Path | None = None,
) -> Path | None:
    """Return a concrete stream network path derived from ``[[data.hydrography.sources]]``."""

    data_cfg = getattr(cfg, "data", None)
    if data_cfg is None:
        return None
    hydrography_cfg = getattr(data_cfg, "hydrography", None)
    if hydrography_cfg is None:
        return None

    sources = getattr(hydrography_cfg, "sources", None) or ()
    config_dir = Path(config_path).resolve().parent

    for source_cfg in sources:
        source_kind = str(getattr(source_cfg, "source", "")).strip()
        if source_kind == "custom":
            resolved = _resolve_custom_path(source_cfg, config_dir)
            if resolved is not None:
                return resolved
        else:
            return _bootstrap_api_source(
                source_cfg,
                cfg=cfg,
                cache_dir=cache_dir,
            )
    return None


def _resolve_custom_path(source_cfg: Any, config_dir: Path) -> Path | None:
    """Return the vector file a ``custom`` source declares, or None when it holds a raster."""
    raw_path = getattr(source_cfg, "path", None)
    if raw_path is None:
        return None
    candidate = Path(str(raw_path)).expanduser()
    if not candidate.is_absolute():
        candidate = (config_dir / candidate).resolve()
    if not candidate.exists():
        raise FileNotFoundError(f"[data.hydrography] custom source path not found: {candidate}")
    if candidate.is_dir():
        candidate = _find_vector_file_in_dir(candidate)
        if candidate is None:
            return None
    if candidate.suffix.lower() in (".tif", ".tiff"):
        logger.info(
            "[data.hydrography] custom source %s is a raster, so it cannot feed the stream "
            "burn, which rasterizes geometries onto the DEM grid itself.",
            candidate,
        )
        return None
    return candidate


def _find_vector_file_in_dir(directory: Path) -> Path | None:
    """Return the first vector file of ``directory``, scaffold templates excluded.

    Deliberately not :func:`~hydromodpy.data.variables.hydrography.custom.load_custom`'s
    scan, which prefers a raster over a vector: the burn needs the linework.
    """
    from hydromodpy.data.common.io_helpers import is_scaffold_example
    from hydromodpy.data.variables.hydrography.custom import _VECTOR_EXTENSIONS

    for extension in _VECTOR_EXTENSIONS:
        for found in sorted(directory.glob(extension)):
            if not is_scaffold_example(found):
                return found
    return None


def _bootstrap_api_source(
    source_cfg: Any,
    *,
    cfg: Any,
    cache_dir: Path | None,
) -> Path:
    """Download the network on an outlet box and return the file it was written to."""
    bbox = _bootstrap_bbox_wgs84(cfg)

    output_dir = (
        Path(cache_dir) if cache_dir is not None else Path(_hmp_cache_dir()) / "hydrography"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    source_kind = str(source_cfg.source).strip()
    # "burn_" prefix, because HydrographyManager writes its own watershed-bbox
    # download in this directory under the bare "<source>_<bbox>.gpkg" name. The
    # two boxes differ, so the names normally differ too, but a tight DEM can
    # round them onto each other and the manager would then overwrite this file.
    out_path = output_dir / (
        f"burn_{source_kind}_{bbox[0]:.4f}_{bbox[1]:.4f}_{bbox[2]:.4f}_{bbox[3]:.4f}.gpkg"
    )
    if out_path.exists() and not bool(getattr(source_cfg, "force_refresh", False)):
        logger.info("Stream burn network already downloaded for this box: %s", out_path)
        return out_path

    from hydromodpy.data.source.port import Extent
    from hydromodpy.data.variables.hydrography.api_source import (
        fetch_network,
        source_from_section,
    )

    source = source_from_section(source_cfg)
    gdf = fetch_network(
        source,
        Extent(xmin=bbox[0], ymin=bbox[1], xmax=bbox[2], ymax=bbox[3], crs="EPSG:4326"),
    )
    if gdf.empty:
        raise ValueError(
            f"[data.hydrography] source {source_kind!r} returned no reach inside the "
            f"bootstrap box {bbox}, so there is nothing to burn. Widen the box by moving "
            "the outlet, or declare geographic.enforce_streams.stream_geometry_path."
        )
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    elif str(gdf.crs) != "EPSG:4326":
        gdf = gdf.to_crs("EPSG:4326")
    gdf.to_file(out_path, driver="GPKG")
    logger.info(
        "Stream burn network downloaded from %s on the outlet box: %d reaches in %s",
        source_kind,
        len(gdf),
        out_path,
    )
    return out_path


def _bootstrap_bbox_wgs84(cfg: Any) -> tuple[float, float, float, float]:
    """Return the WGS84 box the API sources are fetched on.

    Built around the declared outlet, then clipped to the DEM footprint when the
    DEM is already resolved: a reach outside the raster cannot be burned into it,
    and the catchment is a small part of a regional DEM.
    """
    from rasterio.warp import transform_bounds

    geo_cfg = cfg.geographic
    x_outlet = getattr(geo_cfg, "x_outlet", None)
    y_outlet = getattr(geo_cfg, "y_outlet", None)
    if x_outlet is None or y_outlet is None:
        raise ValueError(
            "A hydrography API source can only feed the stream burn when "
            "geographic.x_outlet / y_outlet are declared, since the watershed that would "
            "otherwise give the download box is not delineated yet. Declare "
            "geographic.enforce_streams.stream_geometry_path explicitly instead."
        )

    crs_project = getattr(geo_cfg, "crs_project", None)
    if crs_project is None:
        raise ValueError(
            "geographic.crs_project is required to place the hydrography download box."
        )

    bounds = (
        x_outlet - _BOOTSTRAP_BUFFER_M,
        y_outlet - _BOOTSTRAP_BUFFER_M,
        x_outlet + _BOOTSTRAP_BUFFER_M,
        y_outlet + _BOOTSTRAP_BUFFER_M,
    )
    bounds = _intersect_with_dem(bounds, geo_cfg=geo_cfg, crs_project=crs_project)
    return tuple(transform_bounds(str(crs_project), "EPSG:4326", *bounds))


def _intersect_with_dem(
    bounds: tuple[float, float, float, float],
    *,
    geo_cfg: Any,
    crs_project: Any,
) -> tuple[float, float, float, float]:
    """Clip ``bounds`` to the DEM footprint, or return them unchanged when unknown."""
    import rasterio
    from rasterio.errors import RasterioIOError
    from rasterio.warp import transform_bounds

    dem_path = getattr(geo_cfg, "dem_init_path", None)
    if dem_path is None or not Path(dem_path).exists():
        return bounds
    try:
        with rasterio.open(str(dem_path)) as src:
            dem_bounds = tuple(src.bounds)
            dem_crs = src.crs
    except RasterioIOError:
        return bounds
    if dem_crs is not None and str(dem_crs) != str(crs_project):
        dem_bounds = tuple(transform_bounds(dem_crs, str(crs_project), *dem_bounds))

    clipped = (
        max(bounds[0], dem_bounds[0]),
        max(bounds[1], dem_bounds[1]),
        min(bounds[2], dem_bounds[2]),
        min(bounds[3], dem_bounds[3]),
    )
    if clipped[0] >= clipped[2] or clipped[1] >= clipped[3]:
        raise ValueError(
            f"The outlet box {bounds} does not meet the DEM footprint {dem_bounds}. "
            "Check geographic.x_outlet / y_outlet against the DEM extent."
        )
    return clipped
