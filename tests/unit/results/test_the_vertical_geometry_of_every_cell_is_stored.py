"""A run stores the interfaces and the ``idomain`` of every cell, and how its layers were built."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.exceptions import IncompatibleMeshError
from hydromodpy.results import field_registry
from hydromodpy.results.zarr_store import SimulationZarr
from tests._helpers.ugrid_meshes import quad_mesh

N_CELLS = 4
INTERFACES = np.array(
    [
        [10.0, 11.0, 12.0, 13.0],
        [6.0, 6.5, 7.0, 7.5],
        [0.0, 1.0, 2.0, 3.0],
    ]
)
IDOMAIN = np.array([[1, 0, 1, 1], [1, 1, -1, 1]])


@pytest.fixture
def store(tmp_path):
    handle = SimulationZarr.create(tmp_path / "run.zarr", n_cells=N_CELLS, n_layers=2)
    vertices, connectivity = quad_mesh(2, 2)
    handle.write_mesh(vertices, connectivity, INTERFACES)
    yield handle
    handle.close()


def test_the_solved_geometry_lands_under_mesh(store) -> None:
    store.write_topography(
        INTERFACES[0],
        z_interfaces=INTERFACES,
        n_cells=N_CELLS,
        n_layers=2,
        idomain=IDOMAIN,
        vertical_layout="column_fractions",
    )
    mesh = store.root["mesh"]
    np.testing.assert_array_equal(mesh["z_interfaces"][:], INTERFACES)
    assert mesh["z_interfaces"].metadata.dimension_names == ("layer_interface", "face")
    np.testing.assert_array_equal(mesh["idomain"][:], IDOMAIN)
    assert mesh["idomain"].dtype == np.int8
    assert mesh["idomain"].attrs["flag_values"] == [-1, 0, 1]
    assert mesh.attrs["vertical_layout"] == "column_fractions"
    assert mesh.attrs["n_layers"] == 2


def test_the_idomain_is_a_static_field_of_the_registry(store) -> None:
    store.write_topography(INTERFACES[0], idomain=IDOMAIN)
    descriptor = field_registry.get("idomain")
    assert descriptor.zarr_path == "mesh/idomain"
    assert descriptor.shape == field_registry.SHAPE_LAYER_FACE
    np.testing.assert_array_equal(store.read_field("idomain", 0), IDOMAIN)


def test_an_idomain_value_outside_minus_one_zero_one_is_refused(store) -> None:
    with pytest.raises(ValueError, match="only -1, 0 and 1"):
        store.write_topography(INTERFACES[0], idomain=IDOMAIN * 2)


def test_one_column_given_for_the_mesh_is_the_column_of_every_cell(store) -> None:
    store.write_topography(INTERFACES[0], z_interfaces=np.array([10.0, 0.0]))
    np.testing.assert_array_equal(
        store.root["mesh"]["z_interfaces"][:], np.tile([[10.0], [0.0]], (1, N_CELLS))
    )


def test_interfaces_for_another_cell_count_are_refused(store) -> None:
    with pytest.raises(IncompatibleMeshError, match="3 cells"):
        store.write_topography(INTERFACES[0], z_interfaces=INTERFACES[:, :3])
