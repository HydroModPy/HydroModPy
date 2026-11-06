"""Active cells that no flow path joins are counted and reported, never refused.

Two active cells are joined by a shared face in one layer or by the vertical
connection in one column, through the pass-through cells between them. A lake joins
the cells it is connected to. A group cut off from the rest is a modeling mistake the
solver would not name. The count is made on the grid the solver reads, so after the
lake footprint is made inactive.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import textwrap

import numpy as np

from hydromodpy.solver.modflow6 import build as mf6_build
from hydromodpy.solver.modflow6.builders.lake_cells import apply_lake_idomain_mask
from hydromodpy.solver.modflow_grid import discretization_spatial
from hydromodpy.solver.modflow_grid.active_connectivity import (
    active_component_sizes,
    warn_on_disconnected_active_cells,
)
from hydromodpy.solver.modflow_nwt.nwt.nwt_solver import ModflowNwt
from tests._helpers.mf6_toy_models import regular_solver_mesh
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays


def _two_layers(mask_top: np.ndarray, mask_bottom: np.ndarray):
    """A 3 x 3 grid of two layers with the given inactive masks, row-major."""
    mesh = regular_solver_mesh(3, 3)
    botm = np.vstack([mesh.botm[0], mesh.botm[0] - 1.0])
    inactive = np.vstack([mask_top.reshape(-1), mask_bottom.reshape(-1)]).astype(bool)
    return dataclasses.replace(mesh, botm=botm, idomain=np.where(inactive, 0, 1))


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


def _stack(*layers: np.ndarray):
    """A 3 x 3 grid with one ``idomain`` plane per layer, each a 3 x 3 array, row-major."""
    nlay = len(layers)
    top = np.full((3, 3), 10.0)
    botm = np.stack([np.full((3, 3), 10.0 - (k + 1) * 5.0) for k in range(nlay)])
    mesh = solver_mesh_from_structured_arrays(nrow=3, ncol=3, top=top, botm=botm)
    return dataclasses.replace(mesh, idomain=np.stack([np.asarray(p).reshape(-1) for p in layers]))


def test_a_pass_through_layer_joins_the_layers_above_and_below_it() -> None:
    active, pass_through = np.ones((3, 3), dtype=int), np.full((3, 3), -1)
    assert active_component_sizes(_stack(active, pass_through, active)).tolist() == [18]


def test_an_inactive_layer_cuts_the_column() -> None:
    active, inactive = np.ones((3, 3), dtype=int), np.zeros((3, 3), dtype=int)
    assert active_component_sizes(_stack(active, inactive, active)).tolist() == [9, 9]


def test_a_pass_through_cell_under_an_inactive_one_joins_nothing() -> None:
    inactive, pass_through, active = np.zeros((3, 3)), np.full((3, 3), -1), np.ones((3, 3))
    assert active_component_sizes(_stack(inactive, pass_through, active)).tolist() == [9]


def _lake_across_a_thin_stack():
    """Two layers, the lower one active under the middle column only, a lake on that column."""
    top, bottom = np.ones((3, 3), dtype=int), np.zeros((3, 3), dtype=int)
    bottom[:, 1] = 1
    lake = [1, 4, 7]
    return apply_lake_idomain_mask(_stack(top, bottom), lake_cell_ids_by_lake={"lake": lake}), lake


def test_a_lake_that_takes_the_top_of_its_columns_cuts_the_stack() -> None:
    mesh, _ = _lake_across_a_thin_stack()
    assert active_component_sizes(mesh).tolist() == [3, 3, 3]


def test_the_lake_joins_the_cells_it_is_connected_to() -> None:
    mesh, lake = _lake_across_a_thin_stack()
    assert active_component_sizes(mesh, [lake]).tolist() == [9]


def test_a_group_inside_the_lake_footprint_is_gone_once_the_lake_is_masked(caplog) -> None:
    """Before the mask the footprint holds a group of its own; after it, the count is clean."""
    top, middle, bottom = (np.ones((3, 3), dtype=int) for _ in range(3))
    top[:, 1] = 0
    middle[:, 2] = 0
    stack = _stack(top, middle, bottom)
    assert active_component_sizes(stack).tolist() == [18, 3]

    masked = apply_lake_idomain_mask(stack, lake_cell_ids_by_lake={"lake": [2, 5, 8]})
    with caplog.at_level("WARNING"):
        sizes = warn_on_disconnected_active_cells(masked, [[2, 5, 8]])
    assert sizes.tolist() == [18]
    assert "groups" not in caplog.text


def _called_names(function) -> list[tuple[str, int]]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    return [
        (node.func.id, node.lineno)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]


def test_modflow6_counts_the_groups_after_the_lake_footprint_is_inactive() -> None:
    calls = _called_names(mf6_build._mask_lakes)
    masked = [line for name, line in calls if name == "apply_lake_idomain_mask"]
    counted = [line for name, line in calls if name == "warn_on_disconnected_active_cells"]
    assert len(masked) == 1 and len(counted) == 1
    assert counted[0] > masked[0]


def test_the_shared_grid_build_leaves_the_count_to_the_solver() -> None:
    names = {name for name, _ in _called_names(discretization_spatial.build_spatial_discretization)}
    assert "warn_on_disconnected_active_cells" not in names


def test_modflow_nwt_counts_the_groups_of_its_grid() -> None:
    names = {name for name, _ in _called_names(ModflowNwt._build_spatial_discretization)}
    assert "warn_on_disconnected_active_cells" in names
