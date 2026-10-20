"""The area each lake drains on the D8 grid of the regional flow products.

Without a stream network the catchment runoff has no route to a lake, so each
lake is fed directly: its own share of the basin runoff, rate times area. That
area is the one the lake drains. Giving every lake the whole basin counts the
runoff once per lake.

A cell belongs to the FIRST lake its D8 path meets. A lake sitting downstream
of another therefore takes the ground between the two, not the ground the upper
lake already drains: the upper lake's own outflow is the water that travels on,
and it reaches the lower lake through the outlets the user declared. The
shares are disjoint, so they sum to the part of the basin that drains to a
lake. The ground below the last lake, which drains to no lake, feeds none.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.terrain.port import D8_WBT_OFFSETS

logger = get_logger(__name__)

_MAX_JUMPS = 64
"""Pointer jumps before the walk gives up; 2**64 steps exceed any raster."""


def _receivers(d8: np.ndarray, sink: np.ndarray) -> np.ndarray:
    """Flat index of the cell each cell drains to, itself for a pit, an edge or a sink."""
    n_rows, n_cols = d8.shape
    rows, cols = np.indices(d8.shape)
    receiver = np.arange(d8.size, dtype=np.int64).reshape(d8.shape)
    for code, (d_row, d_col) in D8_WBT_OFFSETS.items():
        next_rows = rows + d_row
        next_cols = cols + d_col
        step = (
            (d8 == code)
            & (next_rows >= 0)
            & (next_rows < n_rows)
            & (next_cols >= 0)
            & (next_cols < n_cols)
        )
        receiver[step] = (next_rows[step] * n_cols + next_cols[step]).astype(np.int64)
    # A lake cell is where the walk ends: what falls in stays in.
    receiver[sink] = np.flatnonzero(sink.ravel())
    return receiver.reshape(-1)


def lake_contributing_areas_m2(
    *,
    d8_pointer_tif: str,
    lake_polygons: Mapping[str, object],
    watershed_polygons: Sequence[object] | None = None,
) -> dict[str, float]:
    """Return, per lake id, the area [m2] whose D8 path ends in that lake first.

    ``lake_polygons`` are in the CRS of the raster. ``watershed_polygons``
    restrict the count to the modelled catchment when given. A lake no D8 path
    reaches holds an area of zero.
    """
    import rasterio
    from rasterio import features

    ids = list(lake_polygons)
    if not ids:
        return {}
    with rasterio.open(d8_pointer_tif) as dataset:
        d8 = np.nan_to_num(dataset.read(1), nan=0.0).astype(np.int64)
        transform = dataset.transform
    shape = d8.shape

    label = np.zeros(shape, dtype=np.int32)
    for number, lake_id in enumerate(ids, start=1):
        polygon = lake_polygons[lake_id]
        mine = features.rasterize(
            [(polygon, 1)], out_shape=shape, transform=transform, fill=0, dtype="uint8"
        ).astype(bool)
        if not mine.any():
            # A footprint smaller than a cell: take the cells it touches.
            mine = features.rasterize(
                [(polygon, 1)],
                out_shape=shape,
                transform=transform,
                fill=0,
                dtype="uint8",
                all_touched=True,
            ).astype(bool)
        label[mine] = number
    sink = label > 0

    root = _receivers(d8, sink)
    for _ in range(_MAX_JUMPS):
        jumped = root[root]
        if np.array_equal(jumped, root):
            break
        root = jumped
    owner = label.reshape(-1)[root]

    counted = np.ones(owner.size, dtype=bool)
    polygons = [polygon for polygon in (watershed_polygons or []) if polygon is not None]
    if polygons:
        counted = (
            features.rasterize(
                ((polygon, 1) for polygon in polygons),
                out_shape=shape,
                transform=transform,
                fill=0,
                dtype="uint8",
            )
            .astype(bool)
            .reshape(-1)
        )

    cell_area = abs(float(transform.a) * float(transform.e))
    counts = np.bincount(owner[counted], minlength=len(ids) + 1)
    areas = {lake_id: float(counts[number]) * cell_area for number, lake_id in enumerate(ids, 1)}
    logger.info(
        "Lake contributing areas on the D8 grid: %s.",
        ", ".join(f"{lake_id} {area / 1.0e6:.3f} km2" for lake_id, area in areas.items()),
    )
    return areas


__all__ = ["lake_contributing_areas_m2"]
