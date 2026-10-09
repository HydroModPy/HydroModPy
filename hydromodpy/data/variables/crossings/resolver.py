"""Bridge between ``[[data.crossings.sources]]`` and the file the notch reads.

Twin of :mod:`~hydromodpy.data.variables.hydrography.resolver`, on the
structures instead of the network. The notch is cut inside the geographic
step, before any data manager, so it cannot read what ``LoadDataStep`` later
produces: it needs a concrete file on disk. Users therefore had to declare the
crossings twice. This resolver fills ``[geographic.crossings] path`` from the
data declaration when the geographic one is left empty.

It returns **one** vector path holding every declared source merged, in the
project CRS, with the fixed columns of the variable. Unlike the hydrography
twin it never hands back the user's own file: a custom file is read and
normalised like the others, so the notch can rely on the columns.

- A downloading source is asked over a bootstrap box around the outlet,
  intersected with the DEM footprint, because the watershed the data manager
  clips against does not exist yet at this point in the pipeline.
- A custom source resolves ``path`` against the TOML directory, and a folder
  gives its first vector file.
- The pages of a download are written to that file as they arrive, so memory is
  bounded by one page whatever the size of the box, and the log carries the
  feature count and the time of each source.
- The merged answer is cached on disk as
  ``crossings_ground_<sources>_<key>.gpkg``. The key hashes the box, the CRS
  and every source (a custom file by its path, size and modification time), so
  a changed input is a new file.

The file is deliberately not registered in the data catalog, for the reasons
the hydrography resolver gives: registering costs a ``hydromodpy.lock`` entry in
frozen mode, and ``subsume_entries`` deletes what a box contains.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from hydromodpy.core.io.atomic_replace import staged_path
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import cache_dir as _hmp_cache_dir

logger = get_logger(__name__)

_BOOTSTRAP_BUFFER_M = 30_000
"""Half-width of the outlet box the API sources are asked over, in metres.

Same value as the DEM and hydrography bootstraps, for the same reason: the only
extent known before the delineation is a box around the declared outlet.
"""

_QUERY_CRS = "EPSG:2154"


def resolve_crossings_path_from_data_sources(
    cfg: Any,
    *,
    config_path: Path,
    cache_dir: Path | None = None,
) -> Path | None:
    """Return the merged crossings file derived from ``[[data.crossings.sources]]``.

    ``None`` when the section declares no source.
    """
    data_cfg = getattr(cfg, "data", None)
    crossings_cfg = getattr(data_cfg, "crossings", None) if data_cfg is not None else None
    sources = list(getattr(crossings_cfg, "sources", None) or ())
    if not sources:
        return None

    crs_project = getattr(cfg.geographic, "crs_project", None)
    if crs_project is None:
        raise ValueError("geographic.crs_project is required to place the crossings.")
    config_dir = Path(config_path).resolve().parent

    api_sources = [source for source in sources if str(source.source) != "custom"]
    bbox = _bootstrap_bbox(cfg, crs_project) if api_sources else None
    custom_files = {
        index: _custom_file(source, config_dir)
        for index, source in enumerate(sources)
        if str(source.source) == "custom"
    }

    output_dir = Path(cache_dir) if cache_dir is not None else Path(_hmp_cache_dir()) / "crossings"
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / _file_name(sources, custom_files, bbox, str(crs_project))
    refresh = any(bool(getattr(source, "force_refresh", False)) for source in api_sources)
    if out_path.exists() and not refresh:
        logger.info("Crossings already merged for this box: %s", out_path)
        return out_path

    with staged_path(out_path) as staged:
        counts = _write_merged(staged, sources, custom_files, bbox, str(crs_project))
        if not sum(counts.values()):
            where = "in the files" if bbox is None else f"inside the bootstrap box {bbox}"
            raise ValueError(
                f"[data.crossings] holds no crossing {where}, so there is nothing to notch. "
                "Move the outlet, or declare geographic.crossings.path explicitly."
            )
    logger.info("Crossings merged from %d source(s): %s in %s", len(sources), counts, out_path)
    return out_path


def _write_merged(
    staged: Path,
    sources: list[Any],
    custom_files: dict[int, Path],
    bbox: tuple[float, float, float, float] | None,
    crs: str,
) -> dict[str, int]:
    """Write every source into *staged*, reprojected to *crs*, and count the records per source."""
    from hydromodpy.data.managers.base_manager_common import SourceContext
    from hydromodpy.data.variables.crossings import custom, records
    from hydromodpy.data.variables.crossings.manager import CrossingsManager

    context = SourceContext(project_extent=None, data_dir=None, config_period=None)
    counts: dict[str, int] = {}
    for index, source in enumerate(sources):
        name = str(source.source)
        started = time.perf_counter()
        if name == "custom":
            pages = [custom.load_custom(source, path=custom_files[index])]
        elif name in CrossingsManager.SOURCES:
            pages = CrossingsManager.SOURCES[name](source, bbox=bbox, context=context)
        else:
            raise ValueError(f"Unknown crossings source: {name}")
        written = records.append_pages(staged, pages, crs)
        counts[name] = counts.get(name, 0) + written
        logger.info(
            "Crossings from %s: %d features in %.1f s", name, written, time.perf_counter() - started
        )
    return counts


def _custom_file(source: Any, config_dir: Path) -> Path:
    """The vector file a custom source declares, ``path`` being relative to the TOML."""
    from hydromodpy.data.variables.crossings import custom

    candidate = Path(str(source.path)).expanduser()
    if not candidate.is_absolute():
        candidate = (config_dir / candidate).resolve()
    return custom.vector_file(candidate)


def _file_name(
    sources: list[Any],
    custom_files: dict[int, Path],
    bbox: tuple[float, float, float, float] | None,
    crs: str,
) -> str:
    """``crossings_ground_<sources>_<key>.gpkg``, the key hashing what the file holds."""
    parts: list[Any] = [crs, None if bbox is None else [round(value, 3) for value in bbox]]
    for index, source in enumerate(sources):
        if index in custom_files:
            stat = custom_files[index].stat()
            parts.append(
                [
                    "custom",
                    str(custom_files[index]),
                    stat.st_size,
                    stat.st_mtime_ns,
                    str(getattr(source, "default_crs", "")),
                ]
            )
        else:
            parts.append([str(source.source), int(getattr(source, "page_size", 0))])
    key = hashlib.sha256(json.dumps(parts).encode()).hexdigest()[:8]
    names = "_".join(dict.fromkeys(str(source.source) for source in sources))
    return f"crossings_ground_{names}_{key}.gpkg"


def _bootstrap_bbox(cfg: Any, crs_project: Any) -> tuple[float, float, float, float]:
    """The box the API sources are asked over, in EPSG:2154.

    Built around the declared outlet, then clipped to the DEM footprint when the
    DEM is already resolved: a crossing outside the raster cannot be notched.
    """
    from rasterio.warp import transform_bounds

    geo_cfg = cfg.geographic
    x_outlet = getattr(geo_cfg, "x_outlet", None)
    y_outlet = getattr(geo_cfg, "y_outlet", None)
    if x_outlet is None or y_outlet is None:
        raise ValueError(
            "A crossings API source can only feed the notch when geographic.catchment.x_outlet / "
            "y_outlet are declared, since the watershed that would otherwise give the "
            "download box is not delineated yet. Declare geographic.crossings.path "
            "explicitly instead."
        )
    bounds = (
        x_outlet - _BOOTSTRAP_BUFFER_M,
        y_outlet - _BOOTSTRAP_BUFFER_M,
        x_outlet + _BOOTSTRAP_BUFFER_M,
        y_outlet + _BOOTSTRAP_BUFFER_M,
    )
    bounds = _intersect_with_dem(bounds, geo_cfg=geo_cfg, crs_project=crs_project)
    return tuple(transform_bounds(str(crs_project), _QUERY_CRS, *bounds))


def _intersect_with_dem(
    bounds: tuple[float, float, float, float],
    *,
    geo_cfg: Any,
    crs_project: Any,
) -> tuple[float, float, float, float]:
    """Clip *bounds* to the DEM footprint, or return them unchanged when unknown."""
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
            "Check geographic.catchment.x_outlet / y_outlet against the DEM extent."
        )
    return clipped
