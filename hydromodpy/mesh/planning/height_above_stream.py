"""Height of each DEM pixel above the stream it drains to, on the DEM grid.

This is the height above the nearest drainage (HAND) of Nobre et al. (2011),
doi:10.1016/j.jhydrol.2011.03.051. A pixel drains along the steepest descent
of a copy of the DEM whose depressions are filled, and its height is its own
elevation minus the elevation of the first stream pixel on that path. The
fill is a priority flood (Barnes, Lehman and Mulla 2014) seeded on the stream
pixels and on the edge of the valid pixels, so every pixel reaches one of
them. The heights are read on the DEM itself, and a pixel below the stream it
drains to (a pit) gets 0. A pixel whose path leaves the grid without meeting a
stream has no height (NaN).
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Sequence

import numpy as np
from rasterio.features import rasterize
from scipy.ndimage import binary_dilation
from shapely.geometry import LineString

from hydromodpy.catchment.drainage.filling import DEFAULT_EPSILON_M
from hydromodpy.catchment.drainage.graph import active_surface_mask
from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.mesh.request import RasterGridSpec

__all__ = ["height_above_stream", "stream_pixels"]

_EIGHT = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))


def stream_pixels(lines: Sequence[LineString], grid: RasterGridSpec) -> np.ndarray:
    """The pixels of *grid* the stream *lines* run through, row 0 north."""
    shapes = [(line, 1) for line in lines if not line.is_empty]
    if not shapes:
        return np.zeros((grid.nrow, grid.ncol), dtype=bool)
    return rasterize(
        shapes,
        out_shape=(grid.nrow, grid.ncol),
        transform=grid.transform,
        fill=0,
        all_touched=False,
        dtype="uint8",
    ).astype(bool)


def height_above_stream(
    elevation: np.ndarray, streams: np.ndarray, *, dx: float, dy: float
) -> np.ndarray:
    """Return the height [m] of each pixel above the first stream pixel it drains to.

    *elevation* is the DEM [m], row 0 north, with NaN or a value below -9000
    where it has none. *streams* marks the stream pixels. *dx* and *dy* are
    the pixel steps [m]. A pixel that reaches no stream, or has no
    elevation, is NaN.
    """
    z = np.asarray(elevation, dtype=float)
    stream = np.asarray(streams, dtype=bool)
    if z.ndim != 2 or stream.shape != z.shape:
        raise MeshRequestError(
            f"the elevation {z.shape} and the stream pixels {stream.shape} differ in shape"
        )
    valid = active_surface_mask(z).reshape(z.shape)
    stream &= valid
    if not stream.any():
        raise MeshRequestError("no stream pixel lies on the DEM: the height above it is undefined")
    edge = (
        valid
        & binary_dilation(
            np.pad(~valid, 1, constant_values=True), structure=np.ones((3, 3), dtype=bool)
        )[1:-1, 1:-1]
    )
    filled = _filled(z, valid, stream | edge)
    receiver = _steepest_receiver(filled, valid, dx=float(dx), dy=float(dy))
    root = _first_stream(receiver, stream.ravel())
    reached = np.flatnonzero(valid.ravel() & stream.ravel()[root])
    height = np.full(z.size, np.nan)
    flat = z.ravel()
    height[reached] = np.maximum(flat[reached] - flat[root[reached]], 0.0)
    return height.reshape(z.shape)


def _filled(z: np.ndarray, valid: np.ndarray, seeds: np.ndarray) -> np.ndarray:
    """*z* with every pixel raised so it holds a strictly lower path to a seed.

    The flood runs on a grid padded by one closed ring, so a neighbor is a
    fixed offset of the flat index. A pixel flooded at or below the level it
    is reached from is raised a millimeter above it.
    """
    nrow, ncol = z.shape
    width = ncol + 2
    padded = np.zeros((nrow + 2, width))
    padded[1:-1, 1:-1] = np.where(valid, z, 0.0)
    level = padded.ravel().tolist()
    closed_mask = np.ones((nrow + 2, width), dtype=bool)
    closed_mask[1:-1, 1:-1] = ~valid
    closed = bytearray(closed_mask.ravel().astype(np.uint8).tobytes())
    seed_mask = np.zeros((nrow + 2, width), dtype=bool)
    seed_mask[1:-1, 1:-1] = seeds
    heap = []
    for index in np.flatnonzero(seed_mask).tolist():
        heap.append((level[index], index))
        closed[index] = 1
    heapq.heapify(heap)
    offsets = [dr * width + dc for dr, dc in _EIGHT]
    epsilon = DEFAULT_EPSILON_M
    pop, push = heapq.heappop, heapq.heappush
    while heap:
        height, index = pop(heap)
        for offset in offsets:
            neighbour = index + offset
            if closed[neighbour]:
                continue
            closed[neighbour] = 1
            if level[neighbour] <= height:
                level[neighbour] = height + epsilon
            push(heap, (level[neighbour], neighbour))
    return np.asarray(level).reshape(nrow + 2, width)[1:-1, 1:-1]


def _steepest_receiver(
    filled: np.ndarray, valid: np.ndarray, *, dx: float, dy: float
) -> np.ndarray:
    """Flat index of the steepest strictly lower neighbor of each pixel, -1 where none is."""
    nrow, ncol = filled.shape
    surface = np.where(valid, filled, np.inf)
    padded = np.pad(surface, 1, constant_values=np.inf)
    index = np.arange(nrow * ncol).reshape(nrow, ncol)
    receiver = np.full((nrow, ncol), -1, dtype=np.int64)
    best = np.zeros((nrow, ncol))
    for dr, dc in _EIGHT:
        neighbour = padded[1 + dr : 1 + dr + nrow, 1 + dc : 1 + dc + ncol]
        with np.errstate(invalid="ignore"):
            slope = (surface - neighbour) / math.hypot(dr * dy, dc * dx)
        steeper = valid & (slope > best)
        receiver[steeper] = index[steeper] + dr * ncol + dc
        best[steeper] = slope[steeper]
    return receiver.ravel()


def _first_stream(receiver: np.ndarray, stream: np.ndarray) -> np.ndarray:
    """The first stream pixel on the path of each pixel, or the pixel where its path ends.

    Pointer doubling: each pass doubles the length of path a pixel jumps,
    so the loop runs about log2 of the longest path.
    """
    step = np.where(stream | (receiver < 0), np.arange(receiver.size), receiver)
    while True:
        jumped = step[step]
        if np.array_equal(jumped, step):
            return step
        step = jumped
