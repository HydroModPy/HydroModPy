"""Lengths and areas of vector layers, measured in one projected CRS.

A layer in a geographic CRS is projected first, so a length is in metres and an
area in square metres whatever CRS the file was written in.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.spatial.geographic.core.catchment_domain import catchment_area_m2

__all__ = [
    "measure_linework_length_m",
    "measure_polygon_area_m2",
    "project_gdf_for_metric_operations",
]


def _coerce_crs(crs_like) -> object | None:
    if crs_like is None:
        return None
    if isinstance(crs_like, str) and crs_like.strip() == "":
        return None
    try:
        from pyproj import CRS

        return CRS.from_user_input(crs_like)
    except Exception:
        return None


def _bounds_look_geographic(gdf) -> bool:
    if gdf is None or gdf.empty:
        return True
    minx, miny, maxx, maxy = [float(v) for v in gdf.total_bounds]
    return (
        np.isfinite([minx, miny, maxx, maxy]).all()
        and minx >= -180.0
        and maxx <= 180.0
        and miny >= -90.0
        and maxy <= 90.0
    )


def project_gdf_for_metric_operations(
    gdf,
    *,
    fallback_crs: str | object | None = None,
):
    """Return *gdf* in one projected CRS suitable for metric operations."""
    if gdf is None or gdf.empty:
        return gdf

    out = gdf.copy()
    source_crs = _coerce_crs(out.crs)
    fallback = _coerce_crs(fallback_crs)

    if source_crs is None and fallback is not None:
        out = out.set_crs(fallback, allow_override=True)
        source_crs = fallback
    elif (
        source_crs is not None
        and getattr(source_crs, "is_geographic", False)
        and not _bounds_look_geographic(out)
        and fallback is not None
    ):
        out = out.set_crs(fallback, allow_override=True)
        source_crs = fallback

    if source_crs is None or getattr(source_crs, "is_projected", False):
        return out

    target = None
    try:
        target = out.estimate_utm_crs()
    except Exception:
        target = None
    if target is None and fallback is not None and getattr(fallback, "is_projected", False):
        target = fallback
    if target is None:
        return out
    return out.to_crs(target)


def measure_linework_length_m(
    gdf,
    *,
    fallback_crs: str | object | None = None,
) -> float:
    """Return total line length in metres after coercing to one metric CRS."""
    if gdf is None or gdf.empty:
        return 0.0
    metric_gdf = project_gdf_for_metric_operations(gdf, fallback_crs=fallback_crs)
    return float(np.sum(np.asarray(metric_gdf.length, dtype=float)))


def measure_polygon_area_m2(
    gdf,
    *,
    fallback_crs: str | object | None = None,
) -> float:
    """Return total polygon area in m² after coercing to one metric CRS."""
    if gdf is None or gdf.empty:
        return 0.0
    return catchment_area_m2(project_gdf_for_metric_operations(gdf, fallback_crs=fallback_crs))
