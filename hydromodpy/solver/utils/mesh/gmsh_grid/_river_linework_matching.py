"""Helpers dedicated to matching exported mesh edges against river linework."""

from __future__ import annotations

from collections.abc import Sequence

from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree


class RiverLineworkMatcher:
    """Fast matcher between short mesh edges and one river polyline network.

    The matcher keeps an STRtree over individual river segments/parts and only
    performs exact distance checks on a small shortlisted subset.
    """

    def __init__(
        self,
        *,
        line_geometries: Sequence[BaseGeometry],
        tolerance: float,
    ) -> None:
        self.tolerance = max(float(tolerance), 1.0e-9)
        self._lines = tuple(
            geometry
            for geometry in line_geometries
            if geometry is not None
            and not bool(getattr(geometry, "is_empty", True))
            and float(getattr(geometry, "length", 0.0)) > 0.0
        )
        self._tree = STRtree(self._lines) if self._lines else None

    @property
    def available(self) -> bool:
        """Tell whether at least one river geometry is available for matching."""
        return bool(self._lines)

    def _has_nearby_line(self, geometry) -> bool:
        if self._tree is None:
            return False
        try:
            raw = self._tree.query(
                geometry,
                predicate="dwithin",
                distance=self.tolerance,
            )
        except Exception:
            return False
        return len(raw) > 0

    def matches_segment(self, segment: LineString | None) -> bool:
        """Return whether one exported edge should be flagged as river."""
        if (
            segment is None
            or not self.available
            or bool(getattr(segment, "is_empty", True))
            or float(getattr(segment, "length", 0.0)) <= 0.0
        ):
            return False

        if not self._has_nearby_line(segment):
            return False

        checkpoints = (
            Point(segment.coords[0]),
            segment.interpolate(0.5, normalized=True),
            Point(segment.coords[-1]),
        )
        for point in checkpoints:
            if not self._has_nearby_line(point):
                return False
        return True


__all__ = ["RiverLineworkMatcher"]
