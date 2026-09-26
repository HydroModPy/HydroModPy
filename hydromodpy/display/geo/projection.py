"""Metric projection of a GeoDataFrame, for maps that measure or overlay networks."""

from __future__ import annotations

__all__ = ["project_gdf_for_metric_operations"]


def project_gdf_for_metric_operations(gdf, *, fallback_crs: str | object | None = None):
    """Return ``gdf`` in a projected CRS, so lengths and areas come out in metres.

    A frame without a CRS takes ``fallback_crs``. A projected frame is returned
    as is. A geographic one goes to its UTM zone, else to ``fallback_crs`` when
    that one is projected.
    """
    if gdf is None or gdf.empty:
        return gdf

    out = gdf.copy()
    source_crs = _coerce_crs(out.crs)
    fallback = _coerce_crs(fallback_crs)
    if source_crs is None and fallback is not None:
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
    return out if target is None else out.to_crs(target)


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
