"""Audit item 9 - grid metadata is resolved from the model post-run."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import numpy as np

from hydromodpy.simulation.extraction.post_run import _resolve_run_grid_metadata
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh


def _triangular_planar_mesh() -> HydroMesh:
    vertices = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 5.0], [0.0, 5.0]], dtype=float)
    connectivity = np.array([[0, 1, 2], [0, 2, 3]], dtype=int)
    return HydroMesh(vertices=vertices, cell_blocks=(CellBlock(CellType.TRIANGLE, connectivity),))


def test_resolve_run_grid_metadata_from_solver_mesh() -> None:
    planar = _triangular_planar_mesh()
    solver_mesh = SimpleNamespace(n_cells=2, nlay=3, is_structured=False, planar_mesh=planar)
    model = SimpleNamespace(solver_mesh=solver_mesh)

    meta = _resolve_run_grid_metadata(model)

    assert meta["n_cells"] == 2
    assert meta["n_layers"] == 3
    assert meta["mesh_topology"] == "unstructured_3d"
    assert meta["bbox"] == [0.0, 0.0, 10.0, 5.0]
    assert len(meta["mesh_hash"]) == 64


def test_resolve_run_grid_metadata_structured_2d_topology() -> None:
    planar = _triangular_planar_mesh()
    solver_mesh = SimpleNamespace(n_cells=2, nlay=1, is_structured=True, planar_mesh=planar)
    meta = _resolve_run_grid_metadata(SimpleNamespace(solver_mesh=solver_mesh))
    assert meta["mesh_topology"] == "structured_2d"


def test_resolve_run_grid_metadata_none_without_solver_mesh() -> None:
    assert _resolve_run_grid_metadata(SimpleNamespace()) is None


def test_the_mesh_hash_of_a_polygon_mesh_reads_the_node_ids_of_each_cell_in_turn() -> None:
    # A quad and a triangle: the -1 padding of the triangle row stays out of the hash,
    # so a run keeps the hash the per-cell node arrays gave before the padded table.
    vertices = np.array([[0, 0], [2, 0], [2, 2], [0, 2], [1, 3]], dtype=float)
    cells = (np.array([0, 1, 2, 3]), np.array([3, 2, 4]))
    planar = HydroMesh(vertices=vertices, cell_blocks=(CellBlock(CellType.POLYGON, cells),))
    solver_mesh = SimpleNamespace(n_cells=2, nlay=1, is_structured=False, planar_mesh=planar)

    meta = _resolve_run_grid_metadata(SimpleNamespace(solver_mesh=solver_mesh))

    node_ids = b"".join(np.asarray(cell, dtype=np.int64).tobytes() for cell in cells)
    assert meta["mesh_hash"] == hashlib.sha256(vertices.tobytes() + node_ids).hexdigest()
