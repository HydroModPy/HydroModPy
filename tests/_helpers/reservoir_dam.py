"""A reservoir closed by a dam, for the cutoff-wall tests. Not public API.

The reservoir is an ellipse along x cut flat at its dam end, ``DAM_X``. A
cutoff-wall trace is a north-south line 300 m long, ``offset`` meters
downstream of that flat shore (negative inside the lake).
"""

from __future__ import annotations

from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box

X0, Y0 = 350_000.0, 6_780_000.0
DAM_X = X0 + 900.0
DOMAIN = box(X0, Y0, X0 + 1200.0, Y0 + 800.0)


def reservoir() -> Polygon:
    """An ellipse along x, 760 m by 300 m, cut flat at ``DAM_X``."""
    ellipse = affinity.scale(Point(0.0, 0.0).buffer(1.0, quad_segs=32), 380.0, 150.0)
    ellipse = affinity.translate(ellipse, X0 + 600.0, Y0 + 400.0)
    return ellipse.intersection(box(X0, Y0, DAM_X, Y0 + 800.0))


def trace(offset: float) -> LineString:
    """A north-south trace ``offset`` meters downstream of the dam shore, 300 m long."""
    return LineString([(DAM_X + offset, Y0 + 250.0), (DAM_X + offset, Y0 + 550.0)])
