"""Unit tests for square mesh geometry and cell definitions."""

from __future__ import annotations

import textwrap
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
from matplotlib import pyplot as plt

from hydromodpy.core.rng import RngManager
from hydromodpy.spatial.field.cases.square.field_mesh_square import FieldMeshSquare
from hydromodpy.spatial.field.meshes import (
    StructuredFieldMesh,
    TriangularStructuredFieldMesh,
    TriangularUnstructuredFieldMesh,
)


def test_structured_mesh_geometry_and_cells():
    mesh = FieldMeshSquare.from_unit_square(target_n_cells=9, mesh_kind="structured")

    assert mesh.kind == "structured"
    assert mesh.shape == (4, 4)
    assert mesh.n_nodes == 16
    assert mesh.n_cells == 9
    assert mesh.triangulation is None

    cells = list(mesh.iter_cells())
    assert len(cells) == 9
    first = cells[0]
    assert first.kind == "quadrilateral"
    assert first.node_indices == (0, 1, 5, 4)
    assert first.vertices.shape == (4, 2)
    assert np.allclose(first.centroid, (1.0 / 6.0, 1.0 / 6.0))


def test_triangular_mesh_geometry_and_cells():
    mesh = FieldMeshSquare.from_unit_square(target_n_cells=18, mesh_kind="triangular_structured")

    assert mesh.kind == "triangular_structured"
    assert mesh.shape == (4, 4)
    assert mesh.n_nodes == 16
    assert mesh.n_cells == 18
    assert mesh.triangulation is not None

    cells = list(mesh.iter_cells())
    assert len(cells) == 18
    first = cells[0]
    assert first.kind == "triangle"
    assert len(first.node_indices) == 3
    assert first.vertices.shape == (3, 2)


def test_to_grid_accepts_node_vector():
    mesh = FieldMeshSquare.from_unit_square(target_n_cells=32, mesh_kind="triangular_structured")
    values = np.arange(mesh.n_nodes, dtype=float)
    as_grid = mesh.to_grid(values)
    assert as_grid.shape == mesh.shape
    assert float(as_grid[0, 0]) == 0.0
    assert float(as_grid[-1, -1]) == float(mesh.n_nodes - 1)


def test_structured_cell_centroids_and_values():
    mesh = FieldMeshSquare.from_unit_square(target_n_cells=9, mesh_kind="structured")

    cx, cy = mesh.cell_centroids()
    assert cx.shape == (3, 3)
    assert cy.shape == (3, 3)
    assert np.allclose(cx[0, 0], 1.0 / 6.0)
    assert np.allclose(cy[0, 0], 1.0 / 6.0)

    values_by_cell = np.arange(mesh.n_cells, dtype=float)
    as_cells = mesh.to_cell_values(values_by_cell)
    assert as_cells.shape == (3, 3)
    assert np.allclose(as_cells[0, 0], 0.0)
    assert np.allclose(as_cells[-1, -1], 8.0)


def test_triangular_cell_values_are_per_cell():
    mesh = FieldMeshSquare.from_unit_square(target_n_cells=18, mesh_kind="triangular_structured")
    values_by_cell = np.arange(mesh.n_cells, dtype=float)
    as_cells = mesh.to_cell_values(values_by_cell)
    assert as_cells.shape == (mesh.n_cells,)
    assert np.allclose(as_cells[0], 0.0)
    assert np.allclose(as_cells[-1], float(mesh.n_cells - 1))


def test_mesh_from_toml(tmp_path: Path):
    path = tmp_path / "mesh.toml"
    path.write_text(
        textwrap.dedent("""
            [mesh]
            kind = "triangular_structured"
            target_n_cells = 50
            """),
        encoding="utf-8",
    )
    mesh = FieldMeshSquare.from_toml(path, section="mesh")
    assert mesh.kind == "triangular_structured"
    assert mesh.shape == (6, 6)
    assert mesh.n_cells == 50


def test_unstructured_triangular_mesh_has_approx_target_cell_count():
    target = 80
    mesh = FieldMeshSquare.from_unit_square(
        target_n_cells=target,
        mesh_kind="triangular_unstructured",
        rng_manager=RngManager(master_seed=7),
    )
    assert mesh.kind == "triangular_unstructured"
    assert mesh.triangulation is not None
    assert mesh.n_cells > 0
    assert abs(mesh.n_cells - target) <= max(8, int(0.20 * target))


def test_square_module_reexports_generic_mesh_classes():
    from hydromodpy.spatial.field.cases.square.field_mesh_square import (
        StructuredFieldMesh as StructuredFieldMeshFromSquare,
    )
    from hydromodpy.spatial.field.cases.square.field_mesh_square import (
        TriangularStructuredFieldMesh as TriangularStructuredFieldMeshFromSquare,
    )
    from hydromodpy.spatial.field.cases.square.field_mesh_square import (
        TriangularUnstructuredFieldMesh as TriangularUnstructuredFieldMeshFromSquare,
    )

    assert StructuredFieldMeshFromSquare is StructuredFieldMesh
    assert TriangularStructuredFieldMeshFromSquare is TriangularStructuredFieldMesh
    assert TriangularUnstructuredFieldMeshFromSquare is TriangularUnstructuredFieldMesh


def test_structured_plot_uses_mesh_coordinate_bounds():
    x_plot = np.array([[10.0, 20.0], [10.0, 20.0]], dtype=float)
    y_plot = np.array([[30.0, 30.0], [50.0, 50.0]], dtype=float)
    mesh = StructuredFieldMesh(x_plot=x_plot, y_plot=y_plot)

    fig, ax = plt.subplots()
    try:
        mesh.plot_cell_values(ax, np.array([[1.0]], dtype=float))
        assert np.allclose(ax.get_xlim(), (10.0, 20.0))
        assert np.allclose(ax.get_ylim(), (30.0, 50.0))
    finally:
        plt.close(fig)
