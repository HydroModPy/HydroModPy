"""The channel bed of the ground G, regularised on the pixels of the channel tree A.

The ground G is read along A, the generated channel network of the run, and
fitted by :func:`~hydromodpy.core.bed_regularization.regularize_bed_on_tree`:
the bed closest to G that never rises downstream. The fit runs on the whole
DEM grid, every A pixel with its receiver on the D8 pointer of the routing
DEM R, and writes the regularised copy of G next to it
(:data:`GROUND_BED_FILENAME`). The model-top clips and the SFR bed both read
that copy, so DRN and SFR see one bed. The routing DEM, A, the catchment and
the mesh are built before and never read it.

The pixel tree: every A pixel of the grid, its receiver the D8 pointer of R, a
root where the pointer leaves A or the grid. The pixels inside a declared lake
are left out: they keep G, the edge entering a lake is a root and the reach
below its outlet is a tree of its own. The pixels a crossing notch lowered
(the footprint the notch wrote) are gaps. A declared weir or dam of the
crossings file, snapped to the nearest A pixel within the crossings
``snap_radius`` and not inside a declared lake, cuts both edges of that pixel.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.windows import Window
from shapely.geometry.base import BaseGeometry

from hydromodpy.core.io.raster_io import write_band
from hydromodpy.core.logging import get_logger
from hydromodpy.core.nodata import valid_cells
from hydromodpy.spatial.geographic.core.channel_bed_fit import BedReport, regularize_channel_bed
from hydromodpy.spatial.geographic.core.ground_corrections import (
    ground_dem_path_from_config,
    notch_enabled,
    notch_footprint_path,
)
from hydromodpy.spatial.geographic.core.ground_inputs import lakes_from_config

logger = get_logger(__name__)

GROUND_BED_FILENAME = "dem_ground_bed.tif"
"""The ground with its channel bed regularised, next to the ground."""

GROUND_BED_REPORT_FILENAME = "dem_ground_bed.json"
"""What the fit found and did, next to the regularised ground."""

BED_SUFFIX = "_bed"
"""A clip of the regularised ground is the clip of G's file name with this before the extension."""

_BARRIER_KINDS = ("weir", "dam")

_ALIGN_TOL_PX = 1.0e-3
"""Largest misalignment, in pixels, between two rasters read on one grid."""

_STREAMS_FULL_NAME = "dem_streams_full.tif"
_STREAMS_PRUNED_FULL_NAME = "dem_streams_pruned_full.tif"


def bed_regularization_enabled(config: object) -> bool:
    """Whether ``[geographic.bed_regularization]`` is on."""
    return bool(getattr(getattr(config, "bed_regularization", None), "enabled", False))


def bed_dem_path(clip_path: str | Path) -> Path:
    """Where the clip of the regularised ground matching the clip *clip_path* of G is written."""
    path = Path(clip_path)
    return path.with_name(f"{path.stem}{BED_SUFFIX}{path.suffix}")


def ground_bed_path(setup: object) -> Path:
    """Where the regularised ground is written."""
    return Path(setup.paths.correcflow_path) / GROUND_BED_FILENAME


def ground_bed_report_path(setup: object) -> Path:
    """Where the report of the fit is written."""
    return Path(setup.paths.correcflow_path) / GROUND_BED_REPORT_FILENAME


def top_dem_path_from_config(config: object, setup: object) -> str:
    """The full-extent DEM the model top and the SFR bed read, without building anything.

    The regularised ground when the option is on, else the ground G.
    """
    if bed_regularization_enabled(config):
        return str(ground_bed_path(setup))
    return ground_dem_path_from_config(config, setup)


WINDOW_MARGIN_M = 2_000.0
"""Margin around the domain extent inside which the bed is fitted, in metres.

The regional grid reaches tens of kilometres beyond the model. A channel there
never enters the model, so fitting it only costs time. The margin keeps the
reaches that cross the domain edge whole near it.
"""


def restrict_to_window(
    channel: np.ndarray,
    transform: Any,
    bounds: tuple[float, float, float, float],
    *,
    margin_m: float,
) -> np.ndarray:
    """Return a copy of *channel* kept only inside *bounds* widened by *margin_m*.

    ``bounds`` is ``(xmin, ymin, xmax, ymax)`` in the CRS of *transform*. A window
    that misses the grid keeps nothing.
    """
    xmin, ymin, xmax, ymax = bounds
    res_x, res_y = float(transform.a), -float(transform.e)
    col0 = int(math.floor((xmin - margin_m - transform.c) / res_x))
    col1 = int(math.ceil((xmax + margin_m - transform.c) / res_x))
    row0 = int(math.floor((transform.f - (ymax + margin_m)) / res_y))
    row1 = int(math.ceil((transform.f - (ymin - margin_m)) / res_y))
    col0, col1 = max(col0, 0), min(col1, channel.shape[1])
    row0, row1 = max(row0, 0), min(row1, channel.shape[0])
    kept = np.zeros_like(channel)
    if col0 < col1 and row0 < row1:
        kept[row0:row1, col0:col1] = channel[row0:row1, col0:col1]
    return kept


def domain_bounds(setup: object) -> tuple[float, float, float, float] | None:
    """Extent of the domain the model computes on, or ``None`` without a watershed on disk.

    The union of the watershed, its buffered copy and the buffered box. The
    buffer can be wider than :data:`WINDOW_MARGIN_M`, and the bed must stay
    fitted on every cell the model computes.
    """
    paths = getattr(setup, "paths", None)
    watershed = getattr(paths, "watershed_shp", None)
    if not watershed or not Path(watershed).exists():
        return None
    import geopandas as gpd

    geographic_path = getattr(paths, "geographic_path", None)
    candidates = [
        watershed,
        getattr(paths, "box_buff", None),
        Path(str(geographic_path)) / "watershed_buff.shp" if geographic_path else None,
    ]
    boxes = [
        gpd.read_file(path).total_bounds for path in candidates if path and Path(path).is_file()
    ]
    boxes = [box for box in boxes if np.all(np.isfinite(box))]
    if not boxes:
        return None
    xmin, ymin = np.min([box[:2] for box in boxes], axis=0)
    xmax, ymax = np.max([box[2:] for box in boxes], axis=0)
    return float(xmin), float(ymin), float(xmax), float(ymax)


def regularized_ground_from_config(
    config: object,
    setup: object,
    *,
    d8_tif: str | Path,
    river_products: object,
) -> Path:
    """Fit the bed on the whole ground G, write the regularised ground and its report.

    Returns the path of the regularised ground, :func:`ground_bed_path`. It is
    G byte for byte off the channel tree, on G's grid and in G's data type.
    """
    section = config.bed_regularization
    ground = Path(ground_dem_path_from_config(config, setup))
    with rasterio.open(ground) as src:
        top = src.read(1)
        profile = src.profile.copy()
        transform = src.transform
        nodata = src.nodata
        shape = (src.height, src.width)
    valid = valid_cells(top, nodata)

    channel_tif = _channel_raster(config, setup, river_products)
    channel_raw, channel_nodata = _read_on_grid(channel_tif, transform, shape, fill=0.0)
    channel = valid_cells(channel_raw, channel_nodata) & (channel_raw > 0)
    del channel_raw
    domain = domain_bounds(setup)
    if domain is not None:
        channel = restrict_to_window(channel, transform, domain, margin_m=WINDOW_MARGIN_M)
    d8_raw, d8_nodata = _read_on_grid(d8_tif, transform, shape, fill=0.0)
    d8 = np.where(valid_cells(d8_raw, d8_nodata), d8_raw, 0)
    del d8_raw
    gap = _notch_footprint(config, setup, transform, shape)
    barriers, crossings_path = _barriers_from_config(config, setup)
    lakes = (
        lakes_from_config(config.enforce_lakes, setup)
        if bool(getattr(getattr(config, "enforce_lakes", None), "enabled", False))
        else []
    )
    snap_radius_m = float(config.crossings.snap_radius)
    report = BedReport(
        parameters={
            "min_slope": float(section.min_slope),
            "snap_radius_m": snap_radius_m,
            "ground": str(ground),
            "channel_raster": str(channel_tif),
            "d8_pointer": str(d8_tif),
            "crossings_path": None if crossings_path is None else str(crossings_path),
            "notch_footprint": gap is not None,
            "window_margin_m": None if domain is None else WINDOW_MARGIN_M,
            "lakes": len(lakes),
        }
    )
    fitted, report = regularize_channel_bed(
        top,
        valid=valid,
        transform=transform,
        channel=channel,
        d8=d8,
        gap=gap,
        barriers=barriers,
        lakes=lakes,
        snap_radius_m=snap_radius_m,
        min_slope=float(section.min_slope),
        report=report,
    )

    out = ground_bed_path(setup)
    for key in ("blockxsize", "blockysize"):
        profile.pop(key, None)
    write_band(out, fitted, profile, driver="GTiff", compress="lzw", tiled=False)
    ground_bed_report_path(setup).write_text(
        json.dumps(report.to_document(), indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    logger.info(report.info_line())
    return out


def _channel_raster(config: object, setup: object, river_products: object) -> Path:
    """The full-extent raster of A: its link ids, else its streams (pruned when pruning)."""
    link = getattr(river_products, "stream_link_id_full_tif", None)
    if link and Path(link).exists():
        return Path(link)
    correcflow = Path(setup.paths.correcflow_path)
    name = (
        _STREAMS_PRUNED_FULL_NAME
        if bool(config.river_network.prune_short_streams)
        else _STREAMS_FULL_NAME
    )
    path = correcflow / name
    if not path.exists():
        raise FileNotFoundError(
            f"[geographic.bed_regularization] reads the channel tree A from {path.name} (or "
            f"the full-extent stream-link raster) in {correcflow}, and neither exists."
        )
    return path


def _read_on_grid(
    path: str | Path, transform: Any, shape: tuple[int, int], *, fill: float
) -> tuple[np.ndarray, float | None]:
    """Read *path* on the grid of *transform* and *shape*, *fill* outside its extent.

    The full-extent rasters of one geographic run share the DEM grid, so this
    is a window read; a raster off that grid is refused.
    """
    with rasterio.open(path) as src:
        src_t = src.transform
        if not (
            math.isclose(src_t.a, transform.a, rel_tol=1e-6)
            and math.isclose(src_t.e, transform.e, rel_tol=1e-6)
        ):
            raise ValueError(f"{path} has another cell size than the ground.")
        col = (transform.c - src_t.c) / src_t.a
        row = (transform.f - src_t.f) / src_t.e
        if abs(col - round(col)) > _ALIGN_TOL_PX or abs(row - round(row)) > _ALIGN_TOL_PX:
            raise ValueError(f"{path} is not aligned with the pixels of the ground.")
        window = Window(round(col), round(row), shape[1], shape[0])
        data = src.read(1, window=window, boundless=True, fill_value=fill)
        return data, src.nodata


def _notch_footprint(
    config: object, setup: object, transform: Any, shape: tuple[int, int]
) -> np.ndarray | None:
    """The pixels the crossing notch lowered, as the notch wrote them."""
    if not notch_enabled(config):
        return None
    path = notch_footprint_path(setup)
    if not path.exists():
        return None
    footprint, _ = _read_on_grid(path, transform, shape, fill=0.0)
    return footprint > 0


def _barriers_from_config(
    config: object, setup: object
) -> tuple[list[tuple[str, str, float, BaseGeometry]], Path | None]:
    """The weirs and dams of the crossings file, in the project CRS."""
    raw = getattr(config.crossings, "path", None)
    if raw is None:
        logger.info(
            "Bed regularisation: no crossings file, so no declared weir or dam cuts the "
            "channel tree. Declare [[data.crossings.sources]] or "
            "[geographic.crossings] path to keep their drops."
        )
        return [], None
    path = Path(raw)
    if not path.exists():
        raise FileNotFoundError(f"geographic.crossings.path points to nothing: {path}")
    import geopandas as gpd

    frame = gpd.read_file(path)
    if "kind" not in frame.columns:
        raise ValueError(f"geographic.crossings.path {path} holds no 'kind' column.")
    if frame.crs is None:
        raise ValueError(f"geographic.crossings.path {path} carries no CRS.")
    crs_project = getattr(setup, "crs_project", None)
    if crs_project is not None:
        frame = frame.to_crs(crs_project)
    kinds = frame["kind"].astype(str).str.strip().str.lower()
    names = frame["name"].astype(str) if "name" in frame.columns else None
    drops = frame["drop_m"] if "drop_m" in frame.columns else None
    barriers: list[tuple[str, str, float, BaseGeometry]] = []
    for position, (kind, geometry) in enumerate(zip(kinds, frame.geometry, strict=True)):
        if kind not in _BARRIER_KINDS or geometry is None or geometry.is_empty:
            continue
        name = "" if names is None else str(names.iloc[position])
        drop = math.nan if drops is None else _float_or_nan(drops.iloc[position])
        barriers.append((kind, name, drop, geometry))
    return barriers, path


def _float_or_nan(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return math.nan


__all__ = (
    "BED_SUFFIX",
    "GROUND_BED_FILENAME",
    "GROUND_BED_REPORT_FILENAME",
    "bed_dem_path",
    "bed_regularization_enabled",
    "ground_bed_path",
    "ground_bed_report_path",
    "regularized_ground_from_config",
    "top_dem_path_from_config",
)
