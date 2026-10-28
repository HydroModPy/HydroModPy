"""The top of a solver grid sampled from the DEM by zonal statistics.

The zonal top of a cell reduces the DEM pixels it covers, and falls back to the
centre sample where it covers none. In the centroid mode, a cell a river chain
crosses off its centre still takes the zonal minimum of its pixels, and its
bottom follows that lowered top. A structured grid coarser than its DEM takes
the zonal top when each cell spans enough pixels.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.solver.modflow_grid.sgrid_config import TopSamplingConfig
from hydromodpy.spatial.mesh.cells.zonal_stats import regular_grid_cell_ids, zonal_top
from hydromodpy.spatial.surface import Surface

if TYPE_CHECKING:
    from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh


logger = get_logger(__name__)


def zonal_top_flat(
    *,
    hydro_mesh: object | None = None,
    grid_support: object | None = None,
    active: np.ndarray | None = None,
    top_surface: Surface,
    centroid_top: np.ndarray,
    bottom_flat: np.ndarray,
    nodata: float,
    top_sampling: TopSamplingConfig,
    channel_mask: np.ndarray | None,
    label: str = "Zonal top sampling",
    clamp_to_bottom: bool = True,
) -> np.ndarray:
    """Zonal per-cell top from the DEM; falls back to the centroid sample.

    Reduces every DEM pixel inside each cell (thalweg stat on channel pixels,
    area stat on hillslope pixels) instead of one bilinear sample at the cell
    generator. Requires a fully georeferenced ``top_surface``; without it the
    centroid projection is returned unchanged. The cells are the ``hydro_mesh``
    polygons, or the boxes of the regular grid described by ``grid_support``.
    ``label`` opens the log line. With ``clamp_to_bottom`` a top lowered to within
    ``min_thickness_m`` of ``bottom_flat`` is raised back to that distance; without
    it the caller moves the bottom (see :func:`bottom_under_lowered_top`).
    """
    from rasterio.transform import from_bounds

    support = getattr(top_surface, "support", None)
    fields = ("xmin", "xmax", "ymin", "ymax", "nrows", "ncols")
    if support is None or any(getattr(support, name, None) is None for name in fields):
        logger.warning("Zonal top sampling needs a georeferenced surface; using centroid sample.")
        return centroid_top

    dem = np.asarray(top_surface.as_array(), dtype=float)
    out_shape = (int(support.nrows), int(support.ncols))
    if dem.shape != out_shape:
        logger.warning(
            "Surface array %s does not match its support %s; using centroid sample.",
            dem.shape,
            out_shape,
        )
        return centroid_top
    transform = from_bounds(
        float(support.xmin),
        float(support.ymin),
        float(support.xmax),
        float(support.ymax),
        int(support.ncols),
        int(support.nrows),
    )
    labels = None
    if grid_support is not None:
        labels = regular_grid_cell_ids(
            dem_transform=transform,
            dem_shape=out_shape,
            grid_bounds=(
                float(grid_support.xmin),
                float(grid_support.xmax),
                float(grid_support.ymin),
                float(grid_support.ymax),
            ),
            grid_shape=(int(grid_support.nrows), int(grid_support.ncols)),
        )
    result = zonal_top(
        planar_mesh=hydro_mesh,
        labels=labels,
        active=active,
        dem=dem,
        transform=transform,
        out_shape=out_shape,
        centroid_top=centroid_top,
        nodata=float(nodata),
        channel_mask=channel_mask,
        hillslope_stat=top_sampling.hillslope_stat,
        channel_stat=top_sampling.channel_stat,
        min_pixels=int(top_sampling.min_pixels),
        spike_guard_tol_m=float(top_sampling.spike_guard_tol_m),
        bottom=bottom_flat if clamp_to_bottom else None,
        min_thickness_m=float(top_sampling.min_thickness_m),
    )
    logger.info(
        "%s: %d/%d cells zonal (%d channel), %d lowered "
        "(max -%.2f m, mean -%.2f m), %d spike-reverted, %d thickness-clamped.",
        label,
        int(result.info["n_zonal"]),
        int(result.info["n_cells"]),
        int(result.info["n_channel_cells"]),
        int(result.info["n_lowered"]),
        result.info["max_lowered_m"],
        result.info["mean_lowered_m"],
        int(result.info["n_spike_reverted"]),
        int(result.info["n_thickness_clamped"]),
    )
    return result.top


_MIN_COLUMN_SHARE = 0.1
"""A lowered top keeps at least this share of the column its centre sample gave.

The Flume meshes MODFLOW 6 solves under Newton keep 11.6 % of the centre column at the
least (3.5 m of 30 m); columns of 0.2 to 1.6 m beside 30 m neighbours do not converge.
"""


def bottom_under_lowered_top(
    *,
    top: np.ndarray,
    centroid_top: np.ndarray,
    bottom: np.ndarray,
    min_thickness_m: float,
    nodata: float,
) -> np.ndarray:
    """Bottom that follows a top lowered far under the centre sample.

    The bottom is sampled at the cell centre, the zonal top reduces every pixel
    of the cell. A coarse cell on a pit or a steep valley side can hold a pixel
    tens of metres under its centre sample. Leaving the bottom there keeps a column
    of a few decimetres, whose transmissivity is nil next to the neighbours and
    which MODFLOW 6 cannot solve under Newton. When the lowered top leaves less than
    ``min_thickness_m``, or less than :data:`_MIN_COLUMN_SHARE` of the centre-sample
    column, the bottom moves down with the top and the column keeps the thickness
    of the centre sample. A cell whose top was not lowered, or whose column stays
    thick enough, is untouched, byte for byte.
    """
    valid = (
        np.isfinite(top)
        & np.isfinite(bottom)
        & np.isfinite(centroid_top)
        & (top > float(nodata))
        & (bottom > float(nodata))
        & (centroid_top > float(nodata))
    )
    column = np.maximum(centroid_top - bottom, float(min_thickness_m))
    floor = np.maximum(float(min_thickness_m), _MIN_COLUMN_SHARE * column)
    follows = valid & (top < centroid_top) & (top - bottom < floor)
    if not follows.any():
        return bottom
    lowered = np.where(follows, top - column, bottom)
    logger.info(
        "Zonal top: %d cells would keep less than %.0f %% of their column under their lowered "
        "top; their bottom follows the top (down by up to %.2f m, the centre-sample thickness "
        "kept).",
        int(follows.sum()),
        100.0 * _MIN_COLUMN_SHARE,
        float((bottom - lowered)[follows].max()),
    )
    return lowered


def _crossing_cells(cell_mesh: PlanarCellMesh) -> np.ndarray:
    """Boolean mask of the cells a river chain crosses off their centre.

    A crossing cell is a cell of a ``rivers`` chain with a lateral offset above
    zero: the river runs through it, but its centre lies beside the line. That is
    the pair of cells a contact line crosses a river with, a cell that two thalwegs
    closer than half a cell share, and the end cell of a river that starts near the
    domain boundary. A chain that publishes no offset holds the line in every cell.
    """
    crossing = np.zeros(cell_mesh.n_cells, dtype=bool)
    for chain in cell_mesh.chains("rivers"):
        if chain.offset_m is not None:
            crossing[chain.cell_ids[chain.offset_m > 0.0]] = True
    return crossing


def lower_crossing_cells(
    *,
    cell_mesh: PlanarCellMesh,
    top_surface: Surface,
    centroid_top: np.ndarray,
    bottom_flat: np.ndarray,
    nodata: float,
    top_sampling: TopSamplingConfig | None,
) -> np.ndarray:
    """Top of the centroid mode with the crossing cells at their zonal minimum.

    The sample at the centre of a crossing cell lands beside the river, on a bank.
    Those cells, and only those, take the lowest DEM pixel they hold, the channel
    statistic ``min``, so the river cell keeps its incised low. The other cells keep
    the centroid sample, byte for byte. The caller moves the bottom of a cell whose
    lowered top comes within the minimum thickness of it.
    """
    crossing = _crossing_cells(cell_mesh)
    valid = (
        np.isfinite(centroid_top)
        & np.isfinite(bottom_flat)
        & (centroid_top > float(nodata))
        & (bottom_flat > float(nodata))
    )
    crossing &= valid
    if not crossing.any():
        return centroid_top
    sampling = (top_sampling or TopSamplingConfig()).model_copy(update={"channel_stat": "min"})
    # Every pixel of a crossing cell counts as channel: the river runs through it.
    every_pixel = np.ones(np.asarray(top_surface.as_array()).shape, dtype=bool)
    return zonal_top_flat(
        hydro_mesh=cell_mesh.mesh,
        active=crossing,
        top_surface=top_surface,
        centroid_top=centroid_top,
        bottom_flat=bottom_flat,
        nodata=nodata,
        top_sampling=sampling,
        channel_mask=every_pixel,
        label="Crossing-cell top sampling",
        clamp_to_bottom=False,
    )


def cells_cover_pixels(native_top: Surface, grid_top: Surface, *, min_pixels: float = 2.0) -> bool:
    """True when a grid cell spans at least ``min_pixels`` DEM pixels, else log why not.

    Below that, a pixel centre falls in one cell out of several and the block
    statistic is a checkerboard of raw pixels, so the resample stays.
    """
    pixel_area = native_top.support.cell_area
    cell_area = grid_top.support.cell_area
    if not (np.isfinite(pixel_area) and np.isfinite(cell_area)):
        return True  # no georeferencing: the zonal step warns and keeps the resample
    if pixel_area > 0.0 and cell_area >= min_pixels * pixel_area * (1.0 - 1e-9):
        return True
    logger.info(
        "Zonal top sampling skipped: a grid cell (%.0f m2) covers fewer than %.0f DEM pixels "
        "(%.0f m2 each), so the resampled top is kept.",
        cell_area,
        min_pixels,
        pixel_area,
    )
    return False


def zonal_structured_top(
    *,
    native_top: Surface,
    grid_top: Surface,
    grid_bottom: Surface,
    nodata: float,
    top_sampling: TopSamplingConfig,
    channel_mask: np.ndarray | None,
) -> Surface:
    """Top of a structured grid coarser than its DEM, from the zonal statistics.

    ``native_top`` is the DEM the cells are reduced from, ``grid_top`` its
    resample to the solver grid (fallback and spike reference). Only the values
    of active cells change: a cell the resample left without data stays inactive,
    so the idomain does not move.
    """
    centroid = np.asarray(grid_top.as_array(), dtype=float).reshape(-1)
    dead = ~np.isfinite(centroid) | (centroid <= float(nodata))
    zonal = zonal_top_flat(
        grid_support=grid_top.support,
        active=~dead,
        top_surface=native_top,
        centroid_top=centroid,
        bottom_flat=np.asarray(grid_bottom.as_array(), dtype=float).reshape(-1),
        nodata=nodata,
        top_sampling=top_sampling,
        channel_mask=channel_mask,
    )
    values = np.where(dead, centroid, zonal).reshape(grid_top.as_array().shape)
    return Surface(name=grid_top.name, values=values, support=grid_top.support)
