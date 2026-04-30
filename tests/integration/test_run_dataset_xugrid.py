"""Integration tests for :meth:`hydromodpy.results.run.Run.dataset`.

Covers the three mesh topologies the public API must abstract:

- ``dis``: structured rectangular cells (uniform quads),
- ``disv``: vertex-defined polygons of variable arity,
- ``disu``: unstructured triangle / general mesh.

For each topology, persist a synthetic mesh and one ``head`` field, then
check that ``run.dataset()`` returns an :class:`xugrid.UgridDataset` whose
face dimension matches the mesh's face count and whose values round-trip
the stored array.
"""

from __future__ import annotations

from uuid import uuid4

import numpy as np
import pytest
import xugrid as xu

from hydromodpy.core.exceptions import UnknownFieldError
from hydromodpy.results.catalog import SimulationCatalog
from hydromodpy.results.run import Run


@pytest.fixture
def catalog(tmp_path):
    c = SimulationCatalog(tmp_path / "workspace")
    yield c
    c.close()


def _quad_mesh(nrow: int = 2, ncol: int = 3):
    """Structured quad mesh: ``nrow * ncol`` rectangular cells."""
    nx = ncol + 1
    ny = nrow + 1
    xs = np.tile(np.arange(nx, dtype=float), ny)
    ys = np.repeat(np.arange(ny, dtype=float)[::-1], nx)
    vertices = np.column_stack((xs, ys))
    fnc = np.empty((nrow * ncol, 4), dtype=int)
    idx = 0
    for j in range(nrow):
        for i in range(ncol):
            n00 = j * nx + i
            n10 = j * nx + (i + 1)
            n11 = (j + 1) * nx + (i + 1)
            n01 = (j + 1) * nx + i
            fnc[idx] = [n00, n10, n11, n01]
            idx += 1
    return vertices, fnc


def _disv_mesh():
    """Mixed mesh: one quad and two triangles, padded to width 4."""
    vertices = np.array(
        [
            [0.0, 0.0],
            [1.0, 0.0],
            [1.0, 1.0],
            [0.0, 1.0],
            [2.0, 0.0],
            [2.0, 1.0],
        ],
        dtype=float,
    )
    fnc = np.array(
        [
            [0, 1, 2, 3],
            [1, 4, 2, -1],
            [4, 5, 2, -1],
        ],
        dtype=int,
    )
    return vertices, fnc


def _triangle_mesh():
    """Unstructured triangle mesh: 4 triangles, 5 vertices."""
    vertices = np.array(
        [
            [0.0, 0.0],
            [2.0, 0.0],
            [2.0, 2.0],
            [0.0, 2.0],
            [1.0, 1.0],
        ],
        dtype=float,
    )
    fnc = np.array(
        [
            [0, 1, 4],
            [1, 2, 4],
            [2, 3, 4],
            [3, 0, 4],
        ],
        dtype=int,
    )
    return vertices, fnc


def _persist(catalog, *, topology: str, vertices: np.ndarray, fnc: np.ndarray) -> str:
    sid = str(uuid4())
    n_cells = int(fnc.shape[0])
    n_timesteps = 2
    catalog.register_simulation(
        sid,
        project="dataset_xugrid",
        solver="modflow6",
        mesh_topology=topology,
        n_cells=n_cells,
        n_layers=1,
        n_timesteps=n_timesteps,
    )
    catalog.write_mesh(
        sid,
        vertices=vertices,
        face_node_connectivity=fnc,
        z_interfaces=np.array([0.0, 10.0], dtype=float),
    )
    for t in range(n_timesteps):
        head = np.full((1, n_cells), float(t + 1), dtype="float64")
        catalog.write_field(sid, "head", t, head, n_timesteps=n_timesteps)
    return sid


@pytest.mark.parametrize(
    ("topology", "build_mesh"),
    [
        ("dis", lambda: _quad_mesh(nrow=2, ncol=3)),
        ("disv", _disv_mesh),
        ("disu", _triangle_mesh),
    ],
)
def test_dataset_returns_ugriddataset(catalog, topology, build_mesh):
    vertices, fnc = build_mesh()
    sid = _persist(catalog, topology=topology, vertices=vertices, fnc=fnc)
    run = Run(sid, catalog)

    ds = run.array.dataset()

    assert isinstance(ds, xu.UgridDataset)
    grids = ds.grids
    assert len(grids) == 1
    grid = grids[0]
    assert grid.n_face == fnc.shape[0]
    face_dim = grid.face_dimension
    assert face_dim in ds.dims
    assert ds.sizes[face_dim] == fnc.shape[0]
    assert "head" in ds.data_vars
    head = ds["head"]
    assert head.dims == ("time", "layer", face_dim)
    assert head.shape == (2, 1, fnc.shape[0])
    np.testing.assert_array_equal(head.values[0, 0], np.full(fnc.shape[0], 1.0))
    np.testing.assert_array_equal(head.values[1, 0], np.full(fnc.shape[0], 2.0))
    assert head.attrs["units"] == "m"


def test_dataset_variable_filter(catalog):
    vertices, fnc = _quad_mesh(nrow=2, ncol=2)
    sid = _persist(catalog, topology="dis", vertices=vertices, fnc=fnc)
    run = Run(sid, catalog)

    ds = run.array.dataset(variable="head")

    assert list(ds.data_vars) == ["head"]


def test_dataset_unknown_variable_raises(catalog):
    vertices, fnc = _quad_mesh(nrow=2, ncol=2)
    sid = _persist(catalog, topology="dis", vertices=vertices, fnc=fnc)
    run = Run(sid, catalog)

    with pytest.raises(UnknownFieldError, match="not registered"):
        run.array.dataset(variable="not_a_field")


def test_dataset_missing_variable_raises(catalog):
    vertices, fnc = _quad_mesh(nrow=2, ncol=2)
    sid = _persist(catalog, topology="dis", vertices=vertices, fnc=fnc)
    run = Run(sid, catalog)

    with pytest.raises(KeyError, match="not found"):
        run.array.dataset(variable="watertable_depth")
