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

    candidate_area = float(getattr(candidate_geometry, "area", 0.0) or 0.0)
    selected_area = float(getattr(selected_geometry, "area", 0.0) or 0.0)
    if candidate_area <= 0.0 or selected_area <= 0.0:
        return 0.0

    intersection = candidate_geometry.intersection(selected_geometry)
    intersection_area = float(getattr(intersection, "area", 0.0) or 0.0)
    denominator = _overlap_denominator(
        candidate_area=candidate_area,
        selected_area=selected_area,
        reference=reference,
    )
    if denominator <= 0.0:
        return 0.0
    return intersection_area / denominator


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
