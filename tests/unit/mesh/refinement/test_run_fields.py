"""A field of an earlier run reaches the planner as its extremes over time, per cell.

A threshold is passed when the field went below it, or above it, at some time
step, and never on a cell where the field was undefined. The cells the
threshold selects mark the pixels of the DEM grid whose centre they hold, and
a cell smaller than a pixel still marks the pixel under it.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.spatial.mesh.refinement.run_fields import RunFieldEnvelope, cells_on_grid
from tests._helpers.mesh_cases import grid_spec

_GRID = grid_spec(100, 100, 10.0)
_VERTICES = np.array([[0, 0], [500, 0], [1000, 0], [1000, 1000], [500, 1000], [0, 1000]], float)
_HALVES = np.array([[0, 1, 4, 5], [1, 2, 3, 4]])


def _envelope() -> RunFieldEnvelope:
    """Two cells, west and east halves; the water table came within 0.5 m of the west one."""
    return RunFieldEnvelope(
        sim_id="0123456789abcdef0123456789abcdef",
        run="coarse",
        field="watertable_depth",
        unit="m",
        vertices=_VERTICES,
        connectivity=_HALVES,
        minimum=np.array([0.5, 3.0]),
        maximum=np.array([4.0, 6.0]),
    )


def test_the_threshold_is_passed_at_some_time_step_and_never_on_an_undefined_cell() -> None:
    envelope = dataclasses.replace(
        _envelope(), minimum=np.array([np.nan, 0.2]), maximum=np.array([np.nan, 0.9])
    )

    assert envelope.passing(below=0.5, above=None).tolist() == [False, True]
    assert envelope.passing(below=None, above=0.5).tolist() == [False, True]


@pytest.mark.parametrize(("below", "above"), [(0.5, 0.5), (None, None)], ids=["both", "neither"])
def test_a_threshold_is_below_or_above_and_one_of_them(below, above) -> None:
    with pytest.raises(MeshRequestError, match="either below or above"):
        _envelope().passing(below=below, above=above)


@pytest.mark.parametrize(
    ("minimum", "maximum"),
    [([0.5], [4.0]), ([0.5, 3.0], [4.0]), ([0.5, 3.0, 1.0], [4.0, 6.0, 2.0])],
    ids=["one value", "maxima short", "one value too many"],
)
def test_extremes_that_do_not_hold_one_value_per_cell_are_refused(minimum, maximum) -> None:
    with pytest.raises(MeshRequestError, match="for 2 cells"):
        dataclasses.replace(_envelope(), minimum=np.array(minimum), maximum=np.array(maximum))


def test_the_cells_selected_mark_the_pixels_whose_centre_they_hold() -> None:
    mask = cells_on_grid(_VERTICES, _HALVES, np.array([True, False]), _GRID)

    assert mask[:, :50].all() and not mask[:, 50:].any()


def test_no_cell_selected_marks_no_pixel() -> None:
    assert not cells_on_grid(_VERTICES, _HALVES, np.array([False, False]), _GRID).any()


def test_a_cell_smaller_than_a_pixel_still_marks_the_pixel_under_it() -> None:
    vertices = np.array([[201.0, 201.0], [203.0, 201.0], [203.0, 203.0], [201.0, 203.0]])

    mask = cells_on_grid(vertices, np.array([[0, 1, 2, 3]]), np.array([True]), _GRID)

    assert mask.sum() == 1 and mask[79, 20]


def test_a_cell_off_the_grid_marks_nothing() -> None:
    vertices = np.array([[2001.0, 201.0], [2003.0, 201.0], [2003.0, 203.0], [2001.0, 203.0]])

    mask = cells_on_grid(vertices, np.array([[0, 1, 2, 3]]), np.array([True]), _GRID)

    assert not mask.any()
