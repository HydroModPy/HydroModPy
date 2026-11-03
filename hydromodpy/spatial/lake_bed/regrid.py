"""Conservative resampling of a bathymetry raster onto mesh cells.

The model mesh is usually coarser than the bathymetry raster, so a single
bilinear sample at the cell centroid aliases the fine bed and does not conserve
volume. This module computes a per-cell bed elevation by AREA-style zonal
aggregation: it averages every raster pixel whose center falls inside the cell
polygon. Cells that are finer than the raster (no pixel center inside) fall back
to a bilinear sample so a value is always produced where the raster covers the
cell.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import shapely

from hydromodpy.spatial.lake_bed.abacus import reconcile_bed_to_abacus
from hydromodpy.spatial.surface import Surface
from hydromodpy.spatial.surface_sampling import PreparedSurfaceSampler

__all__ = [
    "cell_bed_from_surface",
    "reconstruct_lake_bed",
]


def cell_bed_from_surface(
    *,
    planar_mesh: object,
    surface: Surface,
    cell_ids: Sequence[int],
    min_pixels: int = 1,
) -> dict[int, float]:
    """Return ``{cell_id: bed_elevation}`` sampled from the bathymetry surface.

    Each cell gets the mean of the raster pixels whose center lies inside the
    cell polygon (zonal mean). When fewer than ``min_pixels`` finite pixels fall
    in the cell, a bilinear sample at the cell centroid is used instead. A cell
    whose centroid also misses the raster support yields ``NaN`` and is left for
    the caller to handle.
    """
    sampler = PreparedSurfaceSampler.from_surface(surface)
    verts = np.asarray(planar_mesh.vertices, dtype=float)
    conn = planar_mesh.flat_connectivity  # one row per cell, -1 padded for polygons

    out: dict[int, float] = {}
    if not sampler.has_complete_support:
        # No georeferencing: nothing zonal is possible, fall back to centroids.
        for cid in cell_ids:
            row = conn[int(cid)]
            poly = verts[row[row >= 0]]
            cx, cy = float(poly[:, 0].mean()), float(poly[:, 1].mean())
            out[int(cid)] = float(sampler.sample(cx, cy))
        return out

    values = sampler.values
    xmin = float(sampler.xmin)
    ymax = float(sampler.ymax)
    dx = float(sampler.dx)
    dy = float(sampler.dy)
    nrows = int(sampler.nrows)
    ncols = int(sampler.ncols)

    for cid in cell_ids:
        row = conn[int(cid)]
        poly = verts[row[row >= 0]]
        bed = _zonal_mean(
            poly=poly,
            values=values,
            xmin=xmin,
            ymax=ymax,
            dx=dx,
            dy=dy,
            nrows=nrows,
            ncols=ncols,
            min_pixels=min_pixels,
        )
        if bed is None or not np.isfinite(bed):
            cx, cy = float(poly[:, 0].mean()), float(poly[:, 1].mean())
            bed = float(sampler.sample(cx, cy))
        out[int(cid)] = float(bed)
    return out


def _zonal_mean(
    *,
    poly: np.ndarray,
    values: np.ndarray,
    xmin: float,
    ymax: float,
    dx: float,
    dy: float,
    nrows: int,
    ncols: int,
    min_pixels: int,
) -> float | None:
    """Mean of the pixels whose center lies inside ``poly``; ``None`` if too few.

    A pixel center on an edge of the polygon is not inside it.
    """
    px_min, py_min = float(poly[:, 0].min()), float(poly[:, 1].min())
    px_max, py_max = float(poly[:, 0].max()), float(poly[:, 1].max())

    # Pixel column / row index window covering the cell bounding box.
    col_lo = int(np.floor((px_min - xmin) / dx))
    col_hi = int(np.ceil((px_max - xmin) / dx))
    row_lo = int(np.floor((ymax - py_max) / dy))
    row_hi = int(np.ceil((ymax - py_min) / dy))
    col_lo = max(col_lo, 0)
    row_lo = max(row_lo, 0)
    col_hi = min(col_hi, ncols - 1)
    row_hi = min(row_hi, nrows - 1)
    if col_hi < col_lo or row_hi < row_lo:
        return None

    cols = np.arange(col_lo, col_hi + 1)
    rows = np.arange(row_lo, row_hi + 1)
    cx = xmin + (cols + 0.5) * dx
    cy = ymax - (rows + 0.5) * dy
    gx, gy = np.meshgrid(cx, cy)
    block = values[row_lo : row_hi + 1, col_lo : col_hi + 1]

    inside = shapely.contains_xy(shapely.Polygon(poly), gx, gy)
    finite = np.isfinite(block)
    keep = inside & finite
    n = int(np.count_nonzero(keep))
    if n < max(1, int(min_pixels)):
        return None
    return float(np.mean(block[keep]))


def reconstruct_lake_bed(
    *,
    planar_mesh: object,
    surface: Surface,
    cell_ids: Sequence[int],
    area_by_cell: Mapping[int, float],
    abacus_stage: Sequence[float],
    abacus_sarea: Sequence[float],
    reconcile: bool = True,
    min_pixels: int = 1,
) -> tuple[dict[int, float], dict[str, float]]:
    """Regrid the bathymetry onto the lake cells and reconcile it to the abacus.

    Returns ``({cell_id: bed_elevation}, diagnostics)``. When ``reconcile`` is
    False the raw regridded bed is returned (still gap-filled), which is useful
    to inspect the bathymetry before the abacus remap.
    """
    raw_bed = cell_bed_from_surface(
        planar_mesh=planar_mesh,
        surface=surface,
        cell_ids=cell_ids,
        min_pixels=min_pixels,
    )
    if not reconcile:
        return raw_bed, {"n_cells": float(len(raw_bed)), "area_scale": 1.0}
    return reconcile_bed_to_abacus(
        bed_by_cell=raw_bed,
        area_by_cell=area_by_cell,
        abacus_stage=abacus_stage,
        abacus_sarea=abacus_sarea,
    )
