"""A ``restart_from`` store is read cell by cell, so it must come from the same mesh.

The guard compares ``mesh/face_node_connectivity`` exactly and ``mesh/vertices``
to half the rounding step flopy writes, and names both mesh identities when the
two differ. A store without a mesh keeps the cell-count rule and a warning.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import zarr

from hydromodpy.core.exceptions import IncompatibleMeshError
from hydromodpy.solver.modflow6.builders import build_start_heads
from hydromodpy.solver.modflow6.builders.initial_conditions import verify_restart_mesh
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from tests._helpers.mf6_toy_models import toy_model
from tests._helpers.regular_cell_meshes import regular_cell_mesh

# Lambert-93 magnitudes: flopy keeps 1e-3 m in x (3.5e5) and 1e-2 m in y (6.8e6).
_XMIN, _YMIN = 350_000.0, 6_800_000.0


def _mesh() -> PlanarCellMesh:
    return regular_cell_mesh(xmin=_XMIN, ymin=_YMIN, dx=100.0, dy=100.0, nrow=2, ncol=3)


def _store(
    path: Path,
    cell_mesh: PlanarCellMesh,
    *,
    vertices: np.ndarray | None = None,
    rows: np.ndarray | None = None,
) -> str:
    """Write the ``head`` and ``mesh/`` groups a prior run leaves, from ``cell_mesh``."""
    root = zarr.open(str(path), mode="w")
    root["head"] = np.arange(cell_mesh.n_cells, dtype=float).reshape(1, 1, -1)
    xy = cell_mesh.mesh.vertices[:, :2] if vertices is None else vertices
    group = root.create_group("mesh")
    group["vertices"] = np.column_stack([xy, np.zeros(len(xy))])
    group["face_node_connectivity"] = (
        cell_mesh.geometry.padded_connectivity if rows is None else rows
    ).astype("int32")
    group.attrs["engine"] = "triangle"
    group.attrs["engine_version"] = "7"
    group.attrs["mesh_request_hash"] = "abcdef0123456789"
    return str(path)


def test_the_same_mesh_restarts(tmp_path: Path) -> None:
    mesh = _mesh()
    verify_restart_mesh(_store(tmp_path / "prior.zarr", mesh), mesh)


def test_a_vertex_moved_by_a_centimetre_is_refused_with_both_identities(tmp_path: Path) -> None:
    mesh = _mesh()
    moved = mesh.mesh.vertices[:, :2].copy()
    moved[4, 0] += 0.01
    prior = _store(tmp_path / "prior.zarr", mesh, vertices=moved)

    with pytest.raises(IncompatibleMeshError) as caught:
        verify_restart_mesh(prior, mesh)

    message = str(caught.value)
    assert "1 vertices moved (first: 4" in message
    assert "engine triangle 7, request abcdef012345" in message
    assert f"engine {mesh.identity.engine_id} {mesh.identity.engine_version}" in message


def test_a_shift_below_half_the_written_step_is_the_same_mesh(tmp_path: Path) -> None:
    """A millimeter in y at 6.8e6 m is under half of flopy's 1e-2 m step there."""
    mesh = _mesh()
    nudged = mesh.mesh.vertices[:, :2].copy()
    nudged[:, 1] += 0.001
    verify_restart_mesh(_store(tmp_path / "prior.zarr", mesh, vertices=nudged), mesh)


def test_the_same_shift_in_x_is_not(tmp_path: Path) -> None:
    """The step at 3.5e5 m is 1e-3 m, so a millimeter in x is a vertex that moved."""
    mesh = _mesh()
    nudged = mesh.mesh.vertices[:, :2].copy()
    nudged[:, 0] += 0.001
    with pytest.raises(IncompatibleMeshError, match="vertices moved"):
        verify_restart_mesh(_store(tmp_path / "prior.zarr", mesh, vertices=nudged), mesh)


def test_two_cells_swapped_are_refused(tmp_path: Path) -> None:
    mesh = _mesh()
    rows = mesh.geometry.padded_connectivity.copy()
    rows[[1, 2]] = rows[[2, 1]]
    prior = _store(tmp_path / "prior.zarr", mesh, rows=rows)

    with pytest.raises(IncompatibleMeshError, match="connectivity differs from cell 1"):
        verify_restart_mesh(prior, mesh)


def test_a_ring_walked_the_other_way_is_the_same_cell(tmp_path: Path) -> None:
    """MODFLOW 6 stores its DISV clockwise: the cell is the same, the ring is reversed."""
    mesh = _mesh()
    rows = mesh.geometry.padded_connectivity.copy()
    rows[:, 1:] = rows[:, :0:-1]
    verify_restart_mesh(_store(tmp_path / "prior.zarr", mesh, rows=rows), mesh)


def test_another_cell_count_is_refused(tmp_path: Path) -> None:
    prior = _store(tmp_path / "prior.zarr", _mesh())
    other = regular_cell_mesh(xmin=_XMIN, ymin=_YMIN, dx=100.0, dy=100.0, nrow=2, ncol=4)

    with pytest.raises(IncompatibleMeshError, match="6 cells .* 8 and"):
        verify_restart_mesh(prior, other)


def test_a_store_without_a_mesh_keeps_the_cell_count_rule_and_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    prior = tmp_path / "prior.zarr"
    zarr.open(str(prior), mode="w")["head"] = np.zeros((1, 1, 6))
    with caplog.at_level(logging.WARNING):
        verify_restart_mesh(str(prior), _mesh())

    assert any("stores no mesh" in record.getMessage() for record in caplog.records)


def _model(restart_from: str) -> SimpleNamespace:
    model = toy_model()
    model.flow = SimpleNamespace(
        initial_conditions=None,
        boundary_conditions={},
        active_bc=[],
        config=SimpleNamespace(restart_from=restart_from),
    )
    return model


def test_the_start_heads_are_not_read_from_another_mesh(tmp_path: Path) -> None:
    mesh = _mesh()
    moved = mesh.mesh.vertices[:, :2].copy()
    moved[0, 0] += 0.5
    prior = _store(tmp_path / "prior.zarr", mesh, vertices=moved)
    solver_mesh = SolverMesh(
        cell_mesh=mesh,
        top=np.full(6, 10.0),
        botm=np.zeros((1, 6)),
        idomain=np.ones((1, 6), dtype=int),
    )

    with pytest.raises(IncompatibleMeshError, match="another mesh"):
        build_start_heads(_model(prior), solver_mesh)


def test_the_start_heads_of_the_same_mesh_are_the_prior_heads(tmp_path: Path) -> None:
    mesh = _mesh()
    prior = _store(tmp_path / "prior.zarr", mesh)
    solver_mesh = SolverMesh(
        cell_mesh=mesh,
        top=np.full(6, 10.0),
        botm=np.zeros((1, 6)),
        idomain=np.ones((1, 6), dtype=int),
    )

    strt = build_start_heads(_model(prior), solver_mesh)

    assert np.array_equal(strt, np.arange(6, dtype=float).reshape(1, 6))
