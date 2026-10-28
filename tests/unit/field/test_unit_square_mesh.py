"""The unit-square planar cell meshes of the field demos."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from pyproj import CRS

from hydromodpy.core.rng import RngManager
from hydromodpy.spatial.field.mesh_cells import mesh_cells
from hydromodpy.spatial.field.unit_square_mesh import UNIT_SQUARE_CRS_WKT, FieldMeshSquare
from tests._helpers.field_cases import write_text


def test_structured_mesh_geometry_and_cells():
    mesh = FieldMeshSquare.from_unit_square(target_n_cells=9, mesh_kind="structured")

    assert mesh.identity.engine_id == "structured"
    assert mesh.mesh.n_nodes == 16
    assert mesh.n_cells == 9
    assert mesh.structured_shape is None

    cells = mesh_cells(mesh)
    assert len(cells) == 9
    first = cells[0]
    assert first.kind == "quadrilateral"
    assert first.node_indices == (0, 1, 5, 4)
    assert first.vertices.shape == (4, 2)
    np.testing.assert_allclose(first.vertices, [[0, 0], [1 / 3, 0], [1 / 3, 1 / 3], [0, 1 / 3]])
    assert np.allclose(first.centroid, (1.0 / 6.0, 1.0 / 6.0))


def test_triangular_mesh_geometry_and_cells():
    mesh = FieldMeshSquare.from_unit_square(target_n_cells=18, mesh_kind="triangular_structured")

    assert mesh.identity.engine_id == "triangular_structured"
    assert mesh.identity.seed is None
    assert mesh.center_kind == "vertex_mean"
    assert mesh.mesh.n_nodes == 16
    assert mesh.n_cells == 18

    cells = mesh_cells(mesh)
    assert len(cells) == 18
    first = cells[0]
    assert first.kind == "triangle"
    assert len(first.node_indices) == 3
    assert first.vertices.shape == (3, 2)
    np.testing.assert_allclose(first.centroid, first.vertices.mean(axis=0))


def test_the_unit_square_crs_is_a_local_engineering_crs():
    mesh = FieldMeshSquare.from_unit_square(target_n_cells=9)

    assert mesh.crs_wkt == UNIT_SQUARE_CRS_WKT
    assert CRS.from_wkt(mesh.crs_wkt).is_engineering


def test_mesh_from_toml(tmp_path: Path):
    path = write_text(
        tmp_path / "mesh.toml", '[mesh]\nkind = "triangular_structured"\ntarget_n_cells = 50'
    )
    mesh = FieldMeshSquare.from_toml(path, section="mesh")
    assert mesh.identity.engine_id == "triangular_structured"
    assert mesh.mesh.n_nodes == 36
    assert mesh.n_cells == 50


def test_unstructured_triangular_mesh_has_approx_target_cell_count():
    target = 80
    manager = RngManager(master_seed=7)
    mesh = FieldMeshSquare.from_unit_square(
        target_n_cells=target,
        mesh_kind="triangular_unstructured",
        rng_manager=manager,
    )
    assert mesh.identity.engine_id == "triangular_unstructured"
    assert mesh.identity.seed == manager.child_seed("spatial.field.square.unstructured_points")
    assert mesh.n_cells > 0
    assert abs(mesh.n_cells - target) <= max(8, int(0.20 * target))


def test_an_unstructured_mesh_without_a_seed_draws_with_42():
    mesh = FieldMeshSquare.from_dict({"kind": "triangular_unstructured", "target_n_cells": 40})

    assert mesh.identity.seed == 42
    again = FieldMeshSquare.from_unit_square(target_n_cells=40, mesh_kind="triangular_unstructured")
    np.testing.assert_array_equal(again.mesh.vertices, mesh.mesh.vertices)


def test_an_unknown_mesh_kind_is_refused():
    with pytest.raises(ValueError, match="Unsupported mesh kind 'hexagonal'"):
        FieldMeshSquare.from_unit_square(target_n_cells=9, mesh_kind="hexagonal")
