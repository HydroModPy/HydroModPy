"""Active cells that no flow path joins are counted and reported, never refused.

Two active cells are joined by a shared face in one layer or by the vertical
connection in one column. A group cut off from the rest is a modelling mistake
the solver would not name.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from hydromodpy.solver.modflow_grid.active_connectivity import (
    active_component_sizes,
    warn_on_disconnected_active_cells,
)

from ._test_modflow6_boundary_conditions_builders import regular_solver_mesh


def _two_layers(mask_top: np.ndarray, mask_bottom: np.ndarray):
    """A 3 x 3 grid of two layers with the given inactive masks, row-major."""
    mesh = regular_solver_mesh(3, 3)
    botm = np.vstack([mesh.botm[0], mesh.botm[0] - 1.0])
    inactive = np.vstack([mask_top.reshape(-1), mask_bottom.reshape(-1)]).astype(bool)
    return dataclasses.replace(mesh, botm=botm, inactive_mask=inactive)


def test_a_fully_active_grid_is_one_group(caplog) -> None:
    mesh = _two_layers(np.zeros((3, 3)), np.zeros((3, 3)))
    with caplog.at_level("WARNING"):
        sizes = warn_on_disconnected_active_cells(mesh)
    assert sizes.tolist() == [18]
    assert "groups" not in caplog.text


def test_an_inactive_column_cuts_the_grid_in_two_and_is_reported(caplog) -> None:
    column = np.zeros((3, 3))
    column[:, 1] = 1
    mesh = _two_layers(column, column)
    with caplog.at_level("WARNING"):
        sizes = warn_on_disconnected_active_cells(mesh)
    assert sizes.tolist() == [6, 6]
    assert "2 groups" in caplog.text
    assert "6, 6" in caplog.text


def test_a_vertical_connection_joins_two_halves_of_the_top_layer() -> None:
    column = np.zeros((3, 3))
    column[:, 1] = 1
    mesh = _two_layers(column, np.zeros((3, 3)))
    assert active_component_sizes(mesh).tolist() == [15]


def test_cells_touching_only_at_a_corner_are_not_joined() -> None:
    top = np.ones((3, 3))
    top[0, 0] = top[1, 1] = top[2, 2] = 0
    mesh = _two_layers(top, np.ones((3, 3)))
    assert active_component_sizes(mesh).tolist() == [1, 1, 1]


def test_a_grid_with_no_active_cell_has_no_group() -> None:
    mesh = _two_layers(np.ones((3, 3)), np.ones((3, 3)))
    assert active_component_sizes(mesh).size == 0
