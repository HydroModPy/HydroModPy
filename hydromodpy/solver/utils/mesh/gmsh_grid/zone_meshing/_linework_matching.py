"""Linework matching helpers used after polygon partitioning."""

from __future__ import annotations

from typing import Mapping

import numpy as np
from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry
from shapely.prepared import prep
from shapely.strtree import STRtree


class SurfaceEmbeddingLocator:
    """Locate the partition face that should receive one embedded curve.

    Internal constraint segments are already noded against the partition before
    this locator is used. In the nominal case, one segment therefore belongs to
    exactly one face. The locator exploits that property:

    - spatially shortlist faces through an STRtree,
    - classify candidates from the segment representative point,
    - fall back to tolerance-based proximity only on the shortlisted faces.

    This keeps the expensive geometry checks away from the previous
    ``segment x all surfaces`` scan.
    """

    def __init__(
        self,
        *,
        surface_polygon_by_tag: Mapping[int, BaseGeometry],
        tolerance: float,
    ) -> None:
        items = [
            (int(surface_tag), polygon)
            for surface_tag, polygon in sorted(surface_polygon_by_tag.items())
            if polygon is not None and not bool(getattr(polygon, "is_empty", True))
        ]
        self._surface_tags = np.array(
            [surface_tag for surface_tag, _ in items],
            dtype=np.int32,
        )
        self._surface_polygons = tuple(polygon for _, polygon in items)
        self._prepared_surfaces = tuple(prep(polygon) for polygon in self._surface_polygons)
        self._tolerance = max(float(tolerance), 1.0e-9)
        self._tree = STRtree(self._surface_polygons) if self._surface_polygons else None

    def locate_surface_tags(self, segment: LineString | None) -> tuple[int, ...]:
        """Return candidate surface tags ordered from most likely to fallback."""
        if (
            segment is None
            or bool(getattr(segment, "is_empty", True))
            or self._tree is None
        ):
            return ()

        probe = segment.representative_point()
        candidate_indices = np.asarray(
            self._tree.query(probe.buffer(self._tolerance)),
            dtype=np.int64,
        ).reshape(-1)
        if candidate_indices.size == 0:
            candidate_indices = np.asarray(
                self._tree.query(segment.envelope.buffer(self._tolerance)),
                dtype=np.int64,
            ).reshape(-1)
        if candidate_indices.size == 0:
            return ()

        exact_matches: list[int] = []
        near_matches: list[tuple[float, int]] = []
        seen_indices: set[int] = set()
        for raw_index in candidate_indices.tolist():
            index = int(raw_index)
            if index in seen_indices:
                continue
            seen_indices.add(index)
            prepared_surface = self._prepared_surfaces[index]
            if prepared_surface.covers(probe):
                exact_matches.append(int(self._surface_tags[index]))
                continue
            surface_polygon = self._surface_polygons[index]
            try:
                probe_distance = float(probe.distance(surface_polygon))
            except Exception:
                continue
            if probe_distance <= self._tolerance:
                near_matches.append((probe_distance, int(self._surface_tags[index])))

        if exact_matches:
            return tuple(exact_matches)
        near_matches.sort(key=lambda item: item[0])
        return tuple(surface_tag for _, surface_tag in near_matches)


def segment_matches_linework(
    *,
    segment: LineString | None,
    linework,
    tolerance: float,
) -> bool:
    """Return whether one mesh segment matches reference linework."""
    if segment is None or linework is None:
        return False
    if segment.is_empty:
        return False
    segment_length = float(segment.length)
    if segment_length <= 0.0:
        return False
    try:
        overlap_length = float(segment.intersection(linework).length)
    except Exception:
        overlap_length = 0.0
    if overlap_length >= 0.995 * segment_length:
        return True
    try:
        return float(segment.distance(linework)) <= max(float(tolerance), 1.0e-9)
    except Exception:
        return False


def segment_intersects_refinement_scope(
    *,
    segment: LineString | None,
    scope_geometry,
    tolerance: float,
) -> bool:
    """Return whether one line segment can influence refinement in one scope."""
    if scope_geometry is None:
        return True
    if segment is None or segment.is_empty:
        return False
    try:
        intersection_geom = segment.intersection(scope_geometry)
        if not intersection_geom.is_empty and float(
            getattr(intersection_geom, "length", 0.0)
        ) > max(float(tolerance), 1.0e-9):
            return True
    except Exception:
        pass
    try:
        if bool(scope_geometry.covers(segment.representative_point())):
            return True
    except Exception:
        pass
    try:
        return float(segment.distance(scope_geometry)) <= max(float(tolerance), 1.0e-9)
    except Exception:
        return False


__all__ = [
    "SurfaceEmbeddingLocator",
    "segment_intersects_refinement_scope",
    "segment_matches_linework",
]
