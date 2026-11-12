"""Move of a gauge onto the most accumulated cell within a radius (m).

The grid is a 5 x 5 V-shaped valley of 100 m cells whose talweg is column 2,
flowing towards the last row. Its drained areas, in cells, are::

    1  2   5  2  1
    1  2  10  2  1
    1  2  15  2  1
    1  2  20  2  1
    1  2  25  2  1
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.calibration.metrics.gauge_snap import GaugeSnapError, snap_to_most_accumulated

N = 5
CELL_M2 = 1.0e4
CELL_M = 100.0


def grid_centres() -> np.ndarray:
    rows, cols = np.mgrid[0:N, 0:N]
    return np.column_stack([CELL_M / 2 + CELL_M * cols.ravel(), CELL_M / 2 + CELL_M * rows.ravel()])


def grid_accumulation() -> np.ndarray:
    acc = np.tile([1.0, 2.0, 0.0, 2.0, 1.0], (N, 1))
    acc[:, 2] = 5.0 * np.arange(1, N + 1)
    return acc.ravel() * CELL_M2


def snap(**overrides):
    call = {
        "centroids": grid_centres(),
        "accumulation": grid_accumulation(),
        "x": 140.0,
        "y": 250.0,
        "radius_m": 120.0,
        "start_index": 11,
    } | overrides
    return snap_to_most_accumulated(**call)


def test_snap_within_the_radius_lands_on_the_talweg():
    result = snap()

    assert result.moved
    assert result.index_after == 2 * N + 2
    assert result.distance_m == pytest.approx(110.0)
    assert result.area_before_m2 == pytest.approx(2 * CELL_M2)
    assert result.area_after_m2 == pytest.approx(15 * CELL_M2)


def test_radius_is_a_maximum_displacement():
    # At 150 m the diagonal talweg cell 148.7 m away is reached, and wins.
    result = snap(radius_m=150.0)

    assert result.index_after == 3 * N + 2
    assert result.distance_m == pytest.approx(np.hypot(110.0, 100.0))


def test_radius_too_small_says_so():
    with pytest.raises(GaugeSnapError, match=r"reaches no cell but the one.*90\.0 m away"):
        snap(radius_m=50.0)


REFUSALS = [
    pytest.param({"radius_m": 0.0}, "radius must be > 0", id="zero radius"),
    pytest.param({"start_index": 99}, "start cell 99 is outside the 25 cells", id="bad start"),
    pytest.param(
        {"accumulation": np.ones(3)}, "25 cell centres and the accumulation 3", id="bad field"
    ),
]


@pytest.mark.parametrize(("overrides", "message"), REFUSALS)
def test_refusals(overrides, message):
    with pytest.raises(ValueError, match=message):
        snap(**overrides)
