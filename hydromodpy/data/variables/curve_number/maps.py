"""The curve number of a land cover grid: each class to the ESA CCI pivot, then its GCN250 row.

The three sources that build a curve number share these steps. Each class code of the grid
goes through the crosswalk of its legend, overridden by the ``classes`` of the section, to
one ESA CCI class. The soil group comes from a letter or a HYSOGs250m raster resampled to
the land cover grid by nearest neighbour. A pixel whose class is left out (sealed, built-up,
water, snow) or whose soil group is unknown is no data, so the mean of a SAFRAN cell reads
the unsealed ground only. A class neither table names is refused with its share of the area.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.core.exceptions import DataProductError
from hydromodpy.data.common.land_cover import (
    CROSSWALKS,
    HYSOGS_CODES,
    LEFT_OUT,
    SOIL_GROUPS,
    curve_number,
    pivot_of,
)

NODATA = -1.0


def crosswalk_of(nomenclature: str, classes: dict[str, int]) -> dict[str, int]:
    """The crosswalk of ``nomenclature`` with the section's rows written over it."""
    return {**CROSSWALKS.get(nomenclature, {}), **classes}


def cache_digest(*parts: Any, hsg_path: Path | None = None) -> str:
    """A short digest of what a map is built from, the soil group file by size and date."""
    stamp = None
    if hsg_path is not None and Path(hsg_path).exists():
        stat = Path(hsg_path).stat()
        stamp = (str(hsg_path), stat.st_size, int(stat.st_mtime))
    text = json.dumps([*(repr(p) for p in parts), stamp], sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def soil_groups(
    shape: tuple[int, int],
    transform: Any,
    crs: str,
    *,
    hsg: str | None,
    hsg_path: Path | None,
) -> np.ndarray:
    """The column of the soil group (0 for A to 3 for D) of each pixel of a grid, -1 where none."""
    if hsg is not None:
        return np.full(shape, SOIL_GROUPS.index(hsg), dtype=np.int8)
    import rasterio
    from rasterio.warp import Resampling, reproject

    codes = np.full(shape, 255, dtype=np.uint8)
    with rasterio.open(str(hsg_path)) as src:
        reproject(
            source=rasterio.band(src, 1),
            destination=codes,
            dst_transform=transform,
            dst_crs=crs,
            dst_nodata=255,
            resampling=Resampling.nearest,
        )
    table = np.full(256, -1, dtype=np.int8)
    for code, column in HYSOGS_CODES.items():
        table[code] = column
    return table[codes]


def curve_number_grid(
    classes: np.ndarray,
    labels: Sequence[str],
    crosswalk: dict[str, int],
    groups: np.ndarray,
    *,
    section: str,
) -> np.ndarray:
    """The curve number of each pixel, ``NODATA`` where its class or soil group gives none.

    ``classes`` holds, for each pixel, an index into ``labels`` (the class codes of the
    legend), or -1 where the land cover has no data.
    """
    counts = np.bincount(classes[classes >= 0], minlength=len(labels))
    pivots = [pivot_of(label, crosswalk) for label in labels]
    unmatched = [i for i, pivot in enumerate(pivots) if pivot is None and counts[i] > 0]
    if unmatched:
        total = counts.sum()
        listed = ", ".join(
            f"{labels[i]} ({100 * counts[i] / total:.1f} %)"
            for i in sorted(unmatched, key=lambda i: -counts[i])
        )
        raise DataProductError(
            f"{section} sends the classes {listed} of the area to no ESA CCI class: add "
            "each one under classes, with 0 to leave it out."
        )
    table = np.full((len(labels) + 1, len(SOIL_GROUPS)), NODATA, dtype=np.float32)
    for i, pivot in enumerate(pivots):
        if pivot in (None, LEFT_OUT):
            continue
        for column in range(len(SOIL_GROUPS)):
            value = curve_number(pivot, column)
            if value is not None:
                table[i, column] = value
    grid = table[np.where(classes >= 0, classes, len(labels)), np.clip(groups, 0, None)]
    return np.where(groups >= 0, grid, NODATA).astype(np.float32)


def write_grid(
    target: Path,
    grid: np.ndarray,
    transform: Any,
    crs: str,
    *,
    tags: dict[str, str] | None = None,
) -> Path:
    """Write ``grid`` as a one-band float32 GeoTIFF with nodata -1, and its *tags*."""
    import rasterio

    from hydromodpy.core.io.atomic_replace import staged_path

    with staged_path(target) as staged:
        with rasterio.open(
            staged,
            "w",
            driver="GTiff",
            width=grid.shape[1],
            height=grid.shape[0],
            count=1,
            dtype="float32",
            crs=crs,
            transform=transform,
            nodata=NODATA,
            compress="deflate",
        ) as out:
            out.write(grid.astype("float32"), 1)
            if tags:
                out.update_tags(**tags)
    return target


def coded(values: np.ndarray, nodata: Any) -> tuple[np.ndarray, list[str]]:
    """The pixels of a numeric class grid as indices into their distinct codes, -1 at nodata."""
    valid = np.ones(values.shape, dtype=bool) if nodata is None else values != nodata
    codes, inverse = np.unique(values[valid], return_inverse=True)
    classes = np.full(values.shape, -1, dtype=np.int64)
    classes[valid] = inverse
    return classes, [str(int(code)) for code in codes]


__all__ = [
    "NODATA",
    "cache_digest",
    "coded",
    "crosswalk_of",
    "curve_number_grid",
    "soil_groups",
    "write_grid",
]
