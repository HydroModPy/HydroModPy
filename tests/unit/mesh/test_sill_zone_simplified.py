"""The sill zone between two lakes is buffered from simplified outlines (C-07)."""

from __future__ import annotations

import time

import numpy as np
from shapely.geometry import Polygon

from hydromodpy.workflow.steps.mesh_inputs import _sill_zone


def _wiggly_lake(cx: float, n: int = 17000) -> Polygon:
    """A lake outline with *n* vertices and metre-scale noise, like a DEM-traced reservoir."""
    rng = np.random.default_rng(0)
    t = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    r = 400.0 + 30.0 * np.sin(7.0 * t) + rng.uniform(-0.5, 0.5, n)
    return Polygon(np.column_stack([cx + r * np.cos(t), r * np.sin(t)]))


def test_sill_zone_is_fast_and_matches_the_raw_buffer():
    first, second = _wiggly_lake(0.0), _wiggly_lake(900.0)
    gap = first.distance(second)
    margin = max(1.5 * gap, 60.0)
    raw = first.buffer(margin).intersection(second.buffer(margin))
    start = time.perf_counter()
    sill_size = max(5.0, 0.4 * gap)
    zone = _sill_zone(first, second, margin, sill_size=sill_size)
    elapsed = time.perf_counter() - start
    # The outline moves by at most the tolerance, a tenth of the sill size, twice.
    assert zone.hausdorff_distance(raw) <= 0.2 * sill_size
    assert elapsed < 0.5 * _raw_time(first, second, margin)


def _raw_time(first: Polygon, second: Polygon, margin: float) -> float:
    start = time.perf_counter()
    first.buffer(margin).intersection(second.buffer(margin))
    return time.perf_counter() - start
