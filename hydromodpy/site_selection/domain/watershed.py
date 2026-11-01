"""Read the watershed vector file that a delineation writes for one catchment.

A delineated catchment names its watershed file in ``watershed_shp``. The file
holds one row per polygon part. Every reader of that file goes through here.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
from shapely.geometry.base import BaseGeometry

from hydromodpy.core.io.crs import same_crs


def read_watershed(path: str | Path, *, crs: str | None = None) -> gpd.GeoDataFrame:
    """Read the watershed file at *path*, one row per part.

    A file that declares no CRS is read in *crs*, and a file in another CRS is
    reprojected to *crs*. Without *crs*, and for a file with no feature, the
    file comes back as written. A missing or unreadable file raises.
    """
    frame = gpd.read_file(str(path))
    if crs is None or frame.empty:
        return frame
    if frame.crs is None:
        return frame.set_crs(crs, allow_override=True)
    if not same_crs(str(frame.crs), crs):
        return frame.to_crs(crs)
    return frame


def watershed_geometry(path: str | Path | None, *, crs: str | None = None) -> BaseGeometry | None:
    """Return the watershed at *path* united into one geometry, in *crs*.

    The result is ``None`` when the path is empty, when the file is missing, and
    when it holds no geometry. *crs* works as in :func:`read_watershed`.
    """
    if not path or not Path(path).is_file():
        return None
    union = read_watershed(path, crs=crs).geometry.union_all()
    return None if union.is_empty else union


def watershed_area_m2(frame: gpd.GeoDataFrame) -> float:
    """Return the summed area of the parts, in the squared unit of the frame CRS."""
    return float(frame.geometry.area.sum())


__all__ = ["read_watershed", "watershed_area_m2", "watershed_geometry"]
