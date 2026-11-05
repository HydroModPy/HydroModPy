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
from pathlib import Path

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.terrain.d8 import d8_receivers

logger = get_logger(__name__)

_MAX_JUMPS = 64
"""Pointer jumps before the walk gives up; 2**64 steps exceed any raster."""


def lake_contributing_areas_m2(
    *,
    d8_pointer_tif: str,
    lake_polygons: Mapping[str, object],
    watershed_polygons: Sequence[object] | None = None,
) -> dict[str, float]:
    """Return, per lake id, the area [m2] whose D8 path ends in that lake first.

    ``lake_polygons`` are in the CRS of the raster. ``watershed_polygons``
    restrict the count to the modeled catchment when given. A lake no D8 path
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

    # A lake cell is where the walk ends: what falls in stays in.
    root = d8_receivers(d8, pit="self")
    root[sink.reshape(-1)] = np.flatnonzero(sink.ravel())
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


def payload_attr(payload: object, name: str) -> object:
    """Read ``name`` from a payload that is a mapping or an object."""
    if isinstance(payload, dict):
        return payload.get(name)
    return getattr(payload, name, None)


def read_watershed_polygons(watershed_shp: object) -> list[object]:
    """Read the delineated watershed polygon(s) used to scope the stream links.

    The full-grid link raster covers the whole regional DEM; only the links
    inside the modeled catchment can map onto the solver mesh.
    """
    if not watershed_shp or not Path(str(watershed_shp)).exists():
        return []
    import geopandas as gpd

    gdf = gpd.read_file(str(watershed_shp))
    return [geometry for geometry in gdf.geometry if geometry is not None]


def lake_areas_or_even_split(
    lakes: Mapping[str, object],
    *,
    d8_pointer_tif: str | None,
    watershed_shp: object,
) -> dict[str, float] | None:
    """Return the area each declared lake drains, or None to split the basin evenly.

    ``lakes`` maps a lake id to its payload (``polygon`` read from a mapping or an
    object). A lake without polygon, or a missing D8 pointer, falls back to None.
    """
    polygons = {
        str(lake_id): payload_attr(payload, "polygon")
        for lake_id, payload in lakes.items()
        if payload_attr(payload, "polygon") is not None
    }
    if len(polygons) != len(lakes) or d8_pointer_tif is None:
        logger.warning(
            "The lakes cannot be given their own drainage area (lake polygons or D8 "
            "pointer missing): the basin runoff is split evenly between them."
        )
        return None
    return lake_contributing_areas_m2(
        d8_pointer_tif=d8_pointer_tif,
        lake_polygons=polygons,
        watershed_polygons=read_watershed_polygons(watershed_shp),
    )


__all__ = [
    "lake_areas_or_even_split",
    "lake_contributing_areas_m2",
    "payload_attr",
    "read_watershed_polygons",
]
