"""The unit-square planar cell meshes of the field demos."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from pyproj import CRS

from hydromodpy.core.state.rng import RngManager
from hydromodpy.spatial.field.mesh_cells import mesh_cells
from hydromodpy.spatial.field.unit_square_mesh import UNIT_SQUARE_CRS_WKT, FieldMeshSquare
from tests._helpers.field_cases import write_text

SEED_7 = RngManager(master_seed=7).child_seed("spatial.field.square.unstructured_points")


@pytest.mark.parametrize(
    ("kind", "n_cells", "center_kind", "cell_kind", "first_nodes"),
    [("structured", 9, "cell_center", "quadrilateral", (0, 1, 5, 4)),
     ("triangular_structured", 18, "vertex_mean", "triangle", None)],
)  # fmt: skip
def test_a_regular_mesh_of_the_square_and_its_cells(kind, n_cells, center_kind, cell_kind, first_nodes):  # fmt: skip
    mesh = FieldMeshSquare.from_unit_square(target_n_cells=n_cells, mesh_kind=kind)

    assert (mesh.identity.engine_id, mesh.identity.seed, mesh.center_kind) == (kind, None, center_kind)  # fmt: skip
    assert (mesh.mesh.n_nodes, mesh.n_cells, mesh.structured_shape) == (16, n_cells, None)
    assert mesh.crs_wkt == UNIT_SQUARE_CRS_WKT
    assert CRS.from_wkt(mesh.crs_wkt).is_engineering
    cells = mesh_cells(mesh)
    corners = 4 if first_nodes else 3
    assert (len(cells), cells[0].kind, len(cells[0].node_indices)) == (n_cells, cell_kind, corners)
    assert cells[0].vertices.shape == (corners, 2)
    np.testing.assert_allclose(cells[0].centroid, cells[0].vertices.mean(axis=0))
    if first_nodes is not None:
        assert cells[0].node_indices == first_nodes
        np.testing.assert_allclose(
            cells[0].vertices, [[0, 0], [1 / 3, 0], [1 / 3, 1 / 3], [0, 1 / 3]]
        )
        assert np.allclose(cells[0].centroid, (1.0 / 6.0, 1.0 / 6.0))


def test_mesh_from_toml(tmp_path: Path):
    toml = '[mesh]\nkind = "triangular_structured"\ntarget_n_cells = 50'
    mesh = FieldMeshSquare.from_toml(write_text(tmp_path / "mesh.toml", toml), section="mesh")
    assert mesh.identity.engine_id == "triangular_structured"
    assert (mesh.mesh.n_nodes, mesh.n_cells) == (36, 50)


@pytest.mark.parametrize(
    ("config", "kind", "n_cells", "seed"),
    [
        ({"mesh_kind": "triangular_unstructured", "approx_n_cells": 40, "rng_seed": 7}, "triangular_unstructured", 40, SEED_7),
        ({"kind": "triangular_unstructured", "target_cell_count": 40, "seed": 7}, "triangular_unstructured", 40, SEED_7),
        ({"target_cell_count": 10}, "structured", 9, None),
    ],
    ids=["rng-seed-and-approx-count", "seed-and-cell-count", "structured-by-default"],
)  # fmt: skip
def test_a_mapping_names_its_cell_count_and_seed_by_any_alias(config, kind, n_cells, seed):
    mesh = FieldMeshSquare.from_dict(config)
    assert (mesh.identity.engine_id, mesh.n_cells, mesh.identity.seed) == (kind, n_cells, seed)


def test_unstructured_triangular_mesh_has_approx_target_cell_count():
    mesh = FieldMeshSquare.from_unit_square(
        target_n_cells=80,
        mesh_kind="triangular_unstructured",
        rng_manager=RngManager(master_seed=7),
    )
    assert (mesh.identity.engine_id, mesh.identity.seed) == ("triangular_unstructured", SEED_7)
    assert abs(mesh.n_cells - 80) <= 16


def test_an_unstructured_mesh_without_a_seed_draws_with_42():
    mesh = FieldMeshSquare.from_dict({"kind": "triangular_unstructured", "target_n_cells": 40})
    assert mesh.identity.seed == 42
    again = FieldMeshSquare.from_unit_square(target_n_cells=40, mesh_kind="triangular_unstructured")
    np.testing.assert_array_equal(again.mesh.vertices, mesh.mesh.vertices)


@pytest.mark.parametrize(
    ("build", "error", "match"),
    [
        (lambda: FieldMeshSquare.from_unit_square(target_n_cells=9, mesh_kind="hexagonal"), ValueError,
         "Unsupported mesh kind 'hexagonal'. Allowed: structured, triangular_structured, "),
        (lambda: FieldMeshSquare.from_dict([("kind", "structured")]), TypeError, "config must be a mapping"),
        (lambda: FieldMeshSquare.from_dict({"kind": "structured"}), KeyError, "requires 'target_n_cells'"),
    ],
    ids=["unknown-kind", "not-a-mapping", "no-cell-count"],
)  # fmt: skip
def test_a_mesh_it_cannot_build_is_refused(build, error, match):
    with pytest.raises(error, match=match):
        build()
