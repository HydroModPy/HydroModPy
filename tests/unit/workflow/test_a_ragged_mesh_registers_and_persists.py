"""A polygon mesh (a Voronoi dual) registers and persists like a triangle mesh.

Its connectivity is a tuple of rows of different lengths: the registration hash
and the Zarr writer both need the ``-1`` padded rectangular rows instead.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from hydromodpy.results.zarr_store import SimulationZarr
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh
from hydromodpy.workflow.steps.prepare_solver import prepare as prepare_module
from hydromodpy.workflow.steps.prepare_solver import validate as validate_module
from tests._helpers.cell_meshes import cell_mesh_of

PADDED = np.array([[0, 1, 2, 3, -1], [1, 4, 5, 6, 2]])


def _square_and_pentagon() -> HydroMesh:
    vertices = np.array(
        [[0, 0], [1, 0], [1, 1], [0, 1], [2, 0], [2.5, 0.5], [2, 1]], dtype=np.float64
    )
    cells = (np.array([0, 1, 2, 3]), np.array([1, 4, 5, 6, 2]))
    return HydroMesh(vertices=vertices, cell_blocks=(CellBlock(CellType.POLYGON, cells),))


def _ctx(cell_mesh: object, z_interfaces: tuple[float, ...] = (0.0, -10.0)) -> SimpleNamespace:
    return SimpleNamespace(
        config_path=None,
        cfg=SimpleNamespace(
            flow=SimpleNamespace(flow_regime="steady"),
            simulation=None,
            geographic=SimpleNamespace(crs_project="EPSG:2154"),
            model_dump=lambda mode="json": {},
        ),
        setup=SimpleNamespace(
            cell_mesh=cell_mesh,
            time_grid=None,
            domain=SimpleNamespace(z_interfaces=np.array(z_interfaces)),
        ),
    )


def test_the_registration_hashes_the_padded_rows_of_a_polygon_mesh() -> None:
    cell_mesh = cell_mesh_of(_square_and_pentagon())

    kwargs = validate_module.collect_registration_kwargs(_ctx(cell_mesh))

    expected = hashlib.sha256(
        cell_mesh.mesh.vertices.tobytes() + PADDED.astype(np.int32).tobytes()
    ).hexdigest()
    assert kwargs["mesh_hash"] == expected
    assert kwargs["n_cells"] == 2
    assert kwargs["mesh_type"] == "polygon"
    assert kwargs["cell_types"] == ["polygon"]


def test_a_polygon_mesh_is_persisted_as_padded_rows(tmp_path: Path) -> None:
    cell_mesh = cell_mesh_of(_square_and_pentagon())
    store = SimulationZarr.create(tmp_path / "sim.zarr", n_cells=2, n_layers=1)
    writer = SimpleNamespace(
        write_mesh=lambda sim_id, **fields: store.write_mesh(**fields),
    )
    try:
        prepare_module.step_persist_mesh(_ctx(cell_mesh), "sim-1", store=writer)

        stored = np.asarray(store.root["mesh"]["face_node_connectivity"][:])
    finally:
        store.close()

    np.testing.assert_array_equal(stored, PADDED)
