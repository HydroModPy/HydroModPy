"""Audit item 9 - grid metadata is resolved from the model post-run."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from hydromodpy.simulation.extraction.post_run import _resolve_run_grid_metadata
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh


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
