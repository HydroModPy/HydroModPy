"""Zonal reduction of a raster onto irregular mesh cells (mesh-agnostic).

Projecting a DEM onto irregular Voronoi/triangle cells by a single bilinear
sample at the cell generator aliases incised channels: the generator often lands
on a bank rather than the thalweg, so channel cells are raised and the drainage
graph gains false pits. This reduces EVERY DEM pixel whose centre falls inside a
cell with a per-class statistic, a thalweg-preserving stat (min/p10) on channel
pixels and an area stat (mean/median) on hillslope pixels, independent of cell
shape (triangle, quad, Voronoi n-gon). It never assumes a cell is a square.

Pixels are assigned to cells by burning each cell polygon id into the DEM grid
(pixel-centre convention), then grouping pixel values by that id. A valid
(non-overlapping) mesh gives each pixel at most one cell.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_PERCENTILE = {"p10": 10.0, "p25": 25.0}
_STATS = ("mean", "median", "min", "max", "p10", "p25")


@dataclass(frozen=True)
class ZonalTopResult:
    """Per-cell conditioned top plus provenance for QC."""

    top: np.ndarray
    """(n_cells,) top elevation (zonal where trusted, centroid fallback elsewhere)."""

    n_pixels: np.ndarray
    """(n_cells,) count of finite DEM pixels inside each cell."""

    n_channel_pixels: np.ndarray
    """(n_cells,) count of finite channel pixels inside each cell."""

    is_channel: np.ndarray
    """(n_cells,) bool: cell holds at least one channel pixel."""

    used_zonal: np.ndarray
    """(n_cells,) bool: cell took a zonal value (not the centroid fallback)."""

    info: dict[str, float]


def rasterize_cell_ids(
    planar_mesh: object,
    *,
    transform,
    out_shape: tuple[int, int],
) -> np.ndarray:
    """Burn each cell polygon id into a raster grid (``fill = -1``).

    A pixel belongs to the cell whose polygon contains its centre. Ragged-safe:
    triangles, quads and Voronoi n-gons are all read from ``flat_connectivity``.
    """
    from rasterio.features import rasterize
    from shapely.geometry import Polygon

    verts = np.asarray(planar_mesh.vertices, dtype=float)[:, :2]
    conn = planar_mesh.flat_connectivity
    n_cells = len(conn)
    shapes = []
    for cid in range(n_cells):
        nodes = np.asarray(conn[cid], dtype=int).reshape(-1)
        if nodes.size < 3:
            continue
        shapes.append((Polygon(verts[nodes]), cid))
    if not shapes:
        return np.full(out_shape, -1, dtype=np.int32)
    return rasterize(
        shapes,
        out_shape=out_shape,
        transform=transform,
        fill=-1,
        all_touched=False,
        dtype=np.int32,
    )


def grouped_reduce(
    labels: np.ndarray,
    values: np.ndarray,
    *,
    n_cells: int,
    stat: str,
) -> np.ndarray:
    """Per-cell statistic over pixels whose label is the cell id (NaN if empty).

    ``labels`` already excludes unwanted pixels by setting them to a negative id;
    only ``0 <= label < n_cells`` pixels contribute.
    """
    if stat not in _STATS:
        raise ValueError(f"Unsupported zonal stat '{stat}'. Allowed: {_STATS}.")
    from scipy import ndimage

    lab = np.asarray(labels, dtype=np.int64)
    vals = np.asarray(values, dtype=float)
    # Drop pixels with a non-finite value or an out-of-range label.
    keep = np.isfinite(vals) & (lab >= 0) & (lab < n_cells)
    lab = np.where(keep, lab, -1)
    index = np.arange(n_cells)
    if stat == "mean":
        out = ndimage.mean(vals, lab, index)
    elif stat == "min":
        out = ndimage.minimum(vals, lab, index)
    elif stat == "max":
        out = ndimage.maximum(vals, lab, index)
    elif stat == "median":
        out = ndimage.median(vals, lab, index)
    else:
        pct = _PERCENTILE[stat]
        out = ndimage.labeled_comprehension(
            vals, lab, index, lambda a: float(np.percentile(a, pct)), float, np.nan
        )
    return np.asarray(out, dtype=float)


def _pixel_counts(labels: np.ndarray, n_cells: int) -> np.ndarray:
    lab = np.asarray(labels, dtype=np.int64).reshape(-1)
    keep = (lab >= 0) & (lab < n_cells)
    return np.bincount(lab[keep], minlength=n_cells)[:n_cells]


def zonal_top(
    *,
    planar_mesh: object,
    dem: np.ndarray,
    transform,
    out_shape: tuple[int, int],
    centroid_top: np.ndarray,
    nodata: float = -9999.0,
    channel_mask: np.ndarray | None = None,
    hillslope_stat: str = "median",
    channel_stat: str = "min",
    min_pixels: int = 3,
    spike_guard_tol_m: float = 2.0,
    bottom: np.ndarray | None = None,
    min_thickness_m: float = 0.1,
) -> ZonalTopResult:
    """Zonal per-cell top from the DEM, thalweg-preserving on channel cells.

    ``centroid_top`` is the current single-sample projection, used as the fallback
    for cells finer than the raster (fewer than ``min_pixels`` pixels), for cells
    the raster does not cover, and as the reference for the hillslope spike guard.
    ``channel_mask`` (same grid as ``dem``) flags channel pixels; a cell holding
    one is reduced with ``channel_stat`` (the incised low), the rest with
    ``hillslope_stat``. ``min_thickness_m`` keeps a lowered top above ``bottom``.
    """
    dem = np.asarray(dem, dtype=float)
    centroid_top = np.asarray(centroid_top, dtype=float).reshape(-1)
    n_cells = int(centroid_top.shape[0])

    labels = rasterize_cell_ids(planar_mesh, transform=transform, out_shape=out_shape)
    finite = np.isfinite(dem) & (dem != float(nodata))
    lab_all = np.where(finite, labels, -1)
    counts = _pixel_counts(lab_all, n_cells)

    hill_val = grouped_reduce(lab_all, dem, n_cells=n_cells, stat=hillslope_stat)

    if channel_mask is not None:
        chan = np.asarray(channel_mask, dtype=bool)
        lab_chan = np.where(finite & chan, labels, -1)
        ch_counts = _pixel_counts(lab_chan, n_cells)
        ch_val = grouped_reduce(lab_chan, dem, n_cells=n_cells, stat=channel_stat)
        is_channel = ch_counts >= 1
    else:
        ch_counts = np.zeros(n_cells, dtype=int)
        ch_val = np.full(n_cells, np.nan)
        is_channel = np.zeros(n_cells, dtype=bool)

    enough = counts >= int(min_pixels)
    use_channel = is_channel & np.isfinite(ch_val) & (counts >= 1)
    use_hill = (~use_channel) & enough & np.isfinite(hill_val)
    top = np.where(use_channel, ch_val, np.where(use_hill, hill_val, centroid_top))
    used_zonal = use_channel | use_hill

    # Spike guard on hillslope cells only: a zonal value far from the centroid
    # sample there signals nodata/edge contamination (channel cells are lowered
    # on purpose, so they are exempt). Fall back to the centroid sample.
    n_spike = 0
    if spike_guard_tol_m > 0:
        bad = (
            use_hill & np.isfinite(centroid_top) & (np.abs(top - centroid_top) > spike_guard_tol_m)
        )
        n_spike = int(np.count_nonzero(bad))
        top = np.where(bad, centroid_top, top)
        used_zonal = used_zonal & ~bad

    # Minimum layer-0 thickness: a lowered channel top must never collide with the
    # aquifer bottom. Raises the top back to bottom + min_thickness where needed.
    n_thickness_clamped = 0
    if bottom is not None and min_thickness_m > 0:
        floor = np.asarray(bottom, dtype=float).reshape(-1) + float(min_thickness_m)
        clamp = np.isfinite(floor) & np.isfinite(top) & (top < floor)
        n_thickness_clamped = int(np.count_nonzero(clamp))
        top = np.where(clamp, floor, top)

    delta = top - centroid_top
    lowered = used_zonal & (delta < -1e-6)
    info = {
        "n_cells": float(n_cells),
        "n_zonal": float(int(used_zonal.sum())),
        "n_channel_cells": float(int(is_channel.sum())),
        "n_centroid_fallback": float(int((~used_zonal).sum())),
        "n_spike_reverted": float(n_spike),
        "n_thickness_clamped": float(n_thickness_clamped),
        "n_lowered": float(int(lowered.sum())),
        "max_lowered_m": float(-delta[lowered].min()) if lowered.any() else 0.0,
        "mean_lowered_m": float(-delta[lowered].mean()) if lowered.any() else 0.0,
    }
    return ZonalTopResult(
        top=top,
        n_pixels=counts,
        n_channel_pixels=ch_counts,
        is_channel=is_channel,
        used_zonal=used_zonal,
        info=info,
    )
