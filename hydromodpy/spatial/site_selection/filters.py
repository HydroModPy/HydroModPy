"""Spatial filtering helpers for site selection."""

from __future__ import annotations

from typing import Literal

OverlapReference = Literal["smaller_basin", "candidate", "selected"]


def basin_overlap_fraction(
    *,
    candidate_geometry: object,
    selected_geometry: object,
    reference: OverlapReference = "smaller_basin",
) -> float:
    """Return overlap fraction between two basin geometries.

    The geometries are expected to be Shapely-like objects exposing ``area`` and
    ``intersection``. No reprojection is performed here; callers must provide
    geometries in a common projected CRS.
    """

    candidate_geometry = _make_overlap_safe_geometry(candidate_geometry)
    selected_geometry = _make_overlap_safe_geometry(selected_geometry)
    if candidate_geometry is None or selected_geometry is None:
        return 0.0

    candidate_area = _geometry_area(candidate_geometry)
    selected_area = _geometry_area(selected_geometry)
    if candidate_area <= 0.0 or selected_area <= 0.0:
        return 0.0

    intersection = _safe_intersection(candidate_geometry, selected_geometry)
    intersection_area = _geometry_area(intersection)
    denominator = _overlap_denominator(
        candidate_area=candidate_area,
        selected_area=selected_area,
        reference=reference,
    )
    if denominator <= 0.0:
        return 0.0
    return intersection_area / denominator


def _geometry_area(geometry: object | None) -> float:
    if geometry is None:
        return 0.0
    try:
        return float(getattr(geometry, "area", 0.0) or 0.0)
    except Exception:
        return 0.0


def _make_overlap_safe_geometry(geometry: object | None) -> object | None:
    if geometry is None:
        return None
    if _is_empty_geometry(geometry):
        return None
    if _is_valid_geometry(geometry):
        return geometry

    repaired = _repair_geometry(geometry)
    if repaired is None or _is_empty_geometry(repaired):
        return None
    return repaired


def _safe_intersection(candidate_geometry: object, selected_geometry: object) -> object | None:
    try:
        return candidate_geometry.intersection(selected_geometry)
    except Exception:
        candidate_geometry = _repair_geometry(candidate_geometry)
        selected_geometry = _repair_geometry(selected_geometry)
        if candidate_geometry is None or selected_geometry is None:
            return None
        try:
            return candidate_geometry.intersection(selected_geometry)
        except Exception:
            return None


def _is_empty_geometry(geometry: object) -> bool:
    try:
        return bool(getattr(geometry, "is_empty", False))
    except Exception:
        return False


def _is_valid_geometry(geometry: object) -> bool:
    try:
        is_valid = geometry.is_valid
    except Exception:
        return True
    try:
        return bool(is_valid)
    except Exception:
        return True


def _repair_geometry(geometry: object) -> object | None:
    make_valid = _load_make_valid()
    if make_valid is not None:
        try:
            repaired = make_valid(geometry)
        except Exception:
            repaired = None
        if repaired is not None and not _is_empty_geometry(repaired):
            return repaired

    buffer = getattr(geometry, "buffer", None)
    if callable(buffer):
        try:
            repaired = buffer(0)
        except Exception:
            repaired = None
        if repaired is not None and not _is_empty_geometry(repaired):
            return repaired

    return geometry


def _load_make_valid():
    try:
        from shapely import make_valid

        return make_valid
    except Exception:
        pass
    try:
        from shapely.validation import make_valid

        return make_valid
    except Exception:
        return None


def is_overlap_allowed(
    *,
    overlap_fraction: float,
    max_pairwise_basin_overlap_fraction: float | None,
) -> bool:
    """Return whether a candidate passes the configured overlap threshold."""

    if max_pairwise_basin_overlap_fraction is None:
        return True
    if max_pairwise_basin_overlap_fraction < 0.0:
        raise ValueError("max_pairwise_basin_overlap_fraction must be >= 0.")
    return overlap_fraction <= max_pairwise_basin_overlap_fraction


def _overlap_denominator(
    *,
    candidate_area: float,
    selected_area: float,
    reference: OverlapReference,
) -> float:
    if reference == "smaller_basin":
        return min(candidate_area, selected_area)
    if reference == "candidate":
        return candidate_area
    if reference == "selected":
        return selected_area
    raise ValueError(f"Unsupported overlap reference: {reference!r}")


__all__ = ["basin_overlap_fraction", "is_overlap_allowed"]
