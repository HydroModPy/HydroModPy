"""Area-weighted mean of a gridded source over the cells of a mesh.

Each pixel of a regular or rectilinear grid weighs on a cell by the area it
shares with the cell polygon. The value of a cell is the mean of the finite
pixels over the part of the cell they cover. A cell rate times the cell area is
then the integral of the source over the cell, so the total over a mesh the grid
covers is the integral of the source over the domain. A cell that shares no area
with a finite pixel gets NaN here, and the caller fills it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from scipy import sparse

from hydromodpy.spatial.mesh.model.geometry import derive_geometry

if TYPE_CHECKING:
    from hydromodpy.spatial.mesh.model.hydro_mesh import HydroMesh

__all__ = ["area_mean", "area_weights"]

_ORIGIN_STEP_M = 1000.0
"""Coordinates are shifted to an origin rounded to the km before any overlay."""

_PAIRS_PER_CHUNK = 100_000
"""Cell-pixel pairs clipped at once, which bounds the memory of the clip arrays."""


def _pixel_edges(centres: np.ndarray, *, axis: str) -> tuple[np.ndarray, bool]:
    """Ascending pixel edges from the pixel centres of one axis, and whether the axis descends.

    An inner edge sits halfway between two centres; an outer edge sits as far
    beyond the outer centre as the first inner edge.
    """
    c = np.asarray(centres, dtype=float).reshape(-1)
    if c.size < 2:
        raise ValueError(
            f"interpolation_method 'area' needs at least two pixel centres along {axis}, "
            f"got {c.size}; the pixel size cannot be read from one centre."
        )
    step = np.diff(c)
    descending = bool(np.all(step < 0))
    if not (descending or np.all(step > 0)):
        raise ValueError(
            f"interpolation_method 'area' needs pixel centres sorted along {axis}; "
            "the source axis is not monotonic."
        )
    if descending:
        c = c[::-1]
    middle = 0.5 * (c[:-1] + c[1:])
    edges = np.concatenate([[2.0 * c[0] - middle[0]], middle, [2.0 * c[-1] - middle[-1]]])
    return edges, descending


def _spans(edges: np.ndarray, low: np.ndarray, high: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """First and past-last ascending pixel index whose span overlaps ``[low, high]``."""
    n = edges.size - 1
    start = np.clip(np.searchsorted(edges, low, side="right") - 1, 0, n)
    stop = np.clip(np.searchsorted(edges, high, side="left"), 0, n)
    return start, np.maximum(stop, start)


def _cell_rings(mesh: HydroMesh) -> np.ndarray:
    """Corners of every cell, ``(n_cells, k, 2)``, a short cell padded with its last corner.

    A repeated corner adds a zero-length edge, which changes no clipped area.
    """
    padded = np.asarray(derive_geometry(mesh).padded_connectivity, dtype=np.int64)
    last = padded[np.arange(padded.shape[0]), (padded >= 0).sum(axis=1) - 1]
    filled = np.where(padded >= 0, padded, last[:, None])
    return np.asarray(mesh.vertices, dtype=float)[filled, :2]


def _clip(rings: np.ndarray, axis: int, bound: np.ndarray, keep_below: bool) -> np.ndarray:
    """Clip every ring by one half-plane (Sutherland-Hodgman), ``(n, m, 2)`` in and out.

    The clip window is convex, so the area of the result is exact for any
    simple ring, convex or not. An empty result is a ring of zeros.
    """
    n, m = rings.shape[:2]
    value = rings[..., axis]
    inside = value <= bound[:, None] if keep_below else value >= bound[:, None]
    following = np.roll(rings, -1, axis=1)
    following_inside = np.roll(inside, -1, axis=1)
    step = following[..., axis] - value
    t = np.divide(bound[:, None] - value, step, out=np.zeros_like(value), where=step != 0.0)
    crossing = rings + t[..., None] * (following - rings)
    slots = np.stack([crossing, following], axis=2).reshape(n, 2 * m, 2)
    valid = np.stack([inside != following_inside, following_inside], axis=2).reshape(n, 2 * m)
    position = np.cumsum(valid, axis=1) - 1
    count = position[:, -1] + 1
    width = max(int(count.max(initial=0)), 1)
    out = np.zeros((n, width, 2))
    row, col = np.nonzero(valid)
    out[row, position[row, col]] = slots[row, col]
    last = out[np.arange(n), np.maximum(count - 1, 0)]
    beyond = np.arange(width)[None, :] >= count[:, None]
    return np.where(beyond[..., None], last[:, None, :], out)


def _clipped_areas(rings: np.ndarray, half_x: np.ndarray, half_y: np.ndarray) -> np.ndarray:
    """Area of each ring inside the box ``[-half_x, half_x] x [-half_y, half_y]``."""
    for axis, half in ((0, half_x), (1, half_y)):
        rings = _clip(rings, axis, half, keep_below=True)
        rings = _clip(rings, axis, -half, keep_below=False)
    following = np.roll(rings, -1, axis=1)
    cross = rings[..., 0] * following[..., 1] - following[..., 0] * rings[..., 1]
    return 0.5 * np.abs(cross.sum(axis=1))


def area_weights(mesh: HydroMesh, source_x: np.ndarray, source_y: np.ndarray) -> sparse.csr_array:
    """Area each pixel shares with each cell, ``(n_cells, ny * nx)`` in m².

    ``source_x`` and ``source_y`` are the 1-D pixel centres of a grid whose
    values are laid out ``(ny, nx)``. Every cell is clipped by every pixel its
    bounding box reaches, in coordinates centred on the pixel so the areas keep
    their digits in a projected CRS.
    """
    x = np.asarray(source_x, dtype=float)
    y = np.asarray(source_y, dtype=float)
    if x.ndim != 1 or y.ndim != 1:
        raise ValueError(
            "interpolation_method 'area' needs a grid with 1-D x and y axes; "
            f"got x of shape {x.shape} and y of shape {y.shape}."
        )
    rings = _cell_rings(mesh)
    origin = np.floor(rings.reshape(-1, 2).min(axis=0) / _ORIGIN_STEP_M) * _ORIGIN_STEP_M
    rings = rings - origin
    x_edges, x_descending = _pixel_edges(x - origin[0], axis="x")
    y_edges, y_descending = _pixel_edges(y - origin[1], axis="y")
    nx, ny = x.size, y.size

    low, high = rings.min(axis=1), rings.max(axis=1)
    x_start, x_stop = _spans(x_edges, low[:, 0], high[:, 0])
    y_start, y_stop = _spans(y_edges, low[:, 1], high[:, 1])
    width = x_stop - x_start
    count = width * (y_stop - y_start)

    cell = np.repeat(np.arange(rings.shape[0]), count)
    rank = np.arange(cell.size) - np.repeat(np.cumsum(count) - count, count)
    ix = x_start[cell] + rank % np.maximum(width[cell], 1)
    iy = y_start[cell] + rank // np.maximum(width[cell], 1)

    shared = np.empty(cell.size, dtype=float)
    for chunk in range(0, cell.size, _PAIRS_PER_CHUNK):
        part = slice(chunk, chunk + _PAIRS_PER_CHUNK)
        cx = 0.5 * (x_edges[ix[part]] + x_edges[ix[part] + 1])
        cy = 0.5 * (y_edges[iy[part]] + y_edges[iy[part] + 1])
        centred = rings[cell[part]] - np.column_stack([cx, cy])[:, None, :]
        shared[part] = _clipped_areas(
            centred,
            0.5 * (x_edges[ix[part] + 1] - x_edges[ix[part]]),
            0.5 * (y_edges[iy[part] + 1] - y_edges[iy[part]]),
        )

    column = np.where(x_descending, nx - 1 - ix, ix)
    row = np.where(y_descending, ny - 1 - iy, iy)
    kept = shared > 0.0
    return sparse.csr_array(
        (shared[kept], (cell[kept], row[kept] * nx + column[kept])),
        shape=(rings.shape[0], ny * nx),
    )


def area_mean(weights: sparse.csr_array, stack: np.ndarray) -> np.ndarray:
    """Area-weighted mean of every slice over every cell, ``(n_slices, n_cells)``.

    Non-finite pixels carry no weight. A cell no finite pixel reaches is NaN.
    """
    flat = np.asarray(stack, dtype=float).reshape(stack.shape[0], -1)
    if flat.shape[1] != weights.shape[1]:
        raise ValueError(
            f"the source slices hold {flat.shape[1]} pixels, the grid axes describe "
            f"{weights.shape[1]}; the values must be laid out (y, x)."
        )
    finite = np.isfinite(flat)
    covered = weights @ finite.T.astype(float)
    total = weights @ np.where(finite, flat, 0.0).T
    mean = np.full(total.shape, np.nan)
    np.divide(total, covered, out=mean, where=covered > 0.0)
    return mean.T
