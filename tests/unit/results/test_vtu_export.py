"""The VTU export of a run: the cells of the store in its order, the field, the run metadata.

``export_vtu`` writes through ``hydromodpy/spatial/mesh/io/vtu.py``, so an
exported run reads back with ``read_vtu`` and ``read_vtu_field_data``: the cells
of the store in its order, with every node, one value per cell, and the run
metadata.
"""

from __future__ import annotations

import meshio
import numpy as np
import pytest

from hydromodpy.results.exporters.vtu import export_vtu
from hydromodpy.results.zarr_store import SimulationZarr
from hydromodpy.results.zarr_store.mesh_layout import mesh_layout_from_cell_mesh
from hydromodpy.spatial.mesh.io.vtu import read_vtu, read_vtu_field_data
from hydromodpy.spatial.mesh.model.cell_types import CellType
from tests._helpers.bundle_cell_meshes import bundle_dual
from tests._helpers.regular_cell_meshes import regular_cell_mesh

# Interleaved node counts with a -1 tail pad: triangle, pentagon, quad, triangle.
_CONNECTIVITY = np.array(
    [
        [0, 1, 2, -1, -1],
        [3, 4, 5, 6, 7],
        [8, 9, 10, 11, -1],
        [12, 13, 14, -1, -1],
    ]
)


def _cell_mesh_store(path, cell_mesh) -> np.ndarray:
    """A store of ``cell_mesh`` with a topography and the run metadata; returns the topography."""
    topography = np.linspace(5.0, 6.0, cell_mesh.n_cells)
    store = SimulationZarr.create(path, n_cells=cell_mesh.n_cells, n_layers=1)
    store.write_crs(crs_wkt="EPSG:2154", epsg_code=2154)
    xy = np.asarray(cell_mesh.mesh.vertices, dtype=float)[:, :2]
    store.write_mesh(
        np.column_stack([xy, np.zeros(len(xy))]),
        cell_mesh.connectivity_rows,
        np.array([0.0, -10.0]),
        topography=topography,
        layout=mesh_layout_from_cell_mesh(cell_mesh, request_hash=""),
    )
    store.root.attrs.update({"license": "CC-BY-4.0", "hydromodpy_version": "1.0.0"})
    store.close()
    return topography


_RUN_METADATA = {
    "sim_id": "a-run",
    "crs_wkt": "EPSG:2154",
    "epsg_code": 2154,
    "license": "CC-BY-4.0",
    "hydromodpy_version": "1.0.0",
}


@pytest.mark.parametrize(
    ("build", "cell_type"),
    [
        (
            lambda: regular_cell_mesh(xmin=0.0, ymin=0.0, dx=25.0, dy=25.0, nrow=3, ncol=4),
            CellType.QUADRILATERAL,
        ),
        (lambda: bundle_dual("stream_depletion_glover_balmer_tri_refined_well"), CellType.POLYGON),
    ],
    ids=["regular", "voronoi"],
)
def test_an_exported_run_reads_back_with_its_cells_its_field_and_its_metadata(
    tmp_path, build, cell_type
):
    cell_mesh = build()
    topography = _cell_mesh_store(tmp_path / "fields.zarr", cell_mesh)

    out = export_vtu(tmp_path / "fields.zarr", "a-run", "topography", 0, tmp_path / "topo.vtu")
    recovered = read_vtu(out)

    assert recovered.cell_types == (cell_type,)
    assert [list(c) for c in recovered.flat_connectivity] == [
        list(c) for c in cell_mesh.mesh.flat_connectivity
    ]
    np.testing.assert_array_equal(recovered.vertices, cell_mesh.mesh.vertices[:, :2])
    np.testing.assert_array_equal(recovered.cell_data["topography"], topography)
    assert read_vtu_field_data(out) == _RUN_METADATA


def test_interleaved_node_counts_keep_every_node_and_their_values(tmp_path):
    store = SimulationZarr.create(tmp_path / "fields.zarr", n_cells=4, n_layers=1)
    nodes = np.random.default_rng(1).random((15, 2))
    store.write_mesh(
        np.column_stack([nodes, np.zeros(15)]),
        _CONNECTIVITY,
        np.array([0.0, -10.0]),
        topography=np.array([10.0, 11.0, 12.0, 13.0]),
    )
    store.close()

    recovered = read_vtu(
        export_vtu(tmp_path / "fields.zarr", "a-run", "topography", 0, tmp_path / "topo.vtu")
    )

    assert recovered.cell_types == (CellType.POLYGON,)
    assert [list(c) for c in recovered.flat_connectivity] == [
        [0, 1, 2],
        [3, 4, 5, 6, 7],
        [8, 9, 10, 11],
        [12, 13, 14],
    ]
    assert recovered.cell_data["topography"].tolist() == [10.0, 11.0, 12.0, 13.0]


def test_values_that_are_not_one_per_cell_are_refused(tmp_path):
    _store(tmp_path / "fields.zarr", crs=True)

    with pytest.raises(ValueError, match="must have 2 values, got 3"):
        export_vtu(
            tmp_path / "fields.zarr",
            "a-run",
            "head",
            0,
            tmp_path / "head.vtu",
            values=np.array([1.0, 2.0, 3.0]),
        )


def _store(path, *, crs: bool) -> None:
    """A store of two triangles with a topography, sealed with a licence and a version."""
    store = SimulationZarr.create(path, n_cells=2, n_layers=1)
    if crs:
        store.write_crs(crs_wkt="EPSG:2154", epsg_code=2154)
    store.write_mesh(
        np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]]),
        np.array([[0, 1, 2], [0, 2, 3]]),
        np.array([0.0, -10.0]),
        topography=np.array([5.0, 6.0]),
    )
    store.root.attrs.update({"license": "CC-BY-4.0", "hydromodpy_version": "1.0.0"})
    store.close()


def _text(array) -> str:
    return bytes(np.asarray(array, dtype=np.uint8)).decode("utf-8")


def test_the_field_data_carries_the_crs_the_run_the_licence_and_the_version(tmp_path):
    _store(tmp_path / "fields.zarr", crs=True)
    out = export_vtu(tmp_path / "fields.zarr", "a-run", "topography", 0, tmp_path / "topo.vtu")
    field_data = meshio.read(out).field_data

    assert _text(field_data["sim_id"]) == "a-run"
    assert _text(field_data["crs_wkt"]) == "EPSG:2154"
    assert field_data["epsg_code"].tolist() == [2154]
    assert _text(field_data["license"]) == "CC-BY-4.0"
    assert _text(field_data["hydromodpy_version"]) == "1.0.0"


def test_pyvista_reads_the_field_data_and_the_cells(tmp_path):
    pv = pytest.importorskip("pyvista")
    _store(tmp_path / "fields.zarr", crs=True)
    out = export_vtu(tmp_path / "fields.zarr", "a-run", "topography", 0, tmp_path / "topo.vtu")
    grid = pv.read(out)

    assert grid.n_cells == 2
    assert _text(grid.field_data["crs_wkt"]) == "EPSG:2154"
    assert np.asarray(grid.field_data["epsg_code"]).tolist() == [2154]
    assert np.asarray(grid.cell_data["topography"]).tolist() == [5.0, 6.0]


def test_the_caller_metadata_wins_and_a_run_without_crs_names_none(tmp_path):
    _store(tmp_path / "fields.zarr", crs=False)
    out = export_vtu(
        tmp_path / "fields.zarr",
        "a-run",
        "topography",
        0,
        tmp_path / "topo.vtu",
        metadata={"hydromodpy_version": "2.0.0", "not_a_field": "x"},
    )
    field_data = meshio.read(out).field_data

    assert _text(field_data["hydromodpy_version"]) == "2.0.0"
    assert "crs_wkt" not in field_data
    assert "epsg_code" not in field_data
    assert "not_a_field" not in field_data


def test_a_legacy_vtk_destination_is_written_without_field_data(tmp_path):
    _store(tmp_path / "fields.zarr", crs=True)
    out = export_vtu(tmp_path / "fields.zarr", "a-run", "topography", 0, tmp_path / "topo.vtk")

    mesh = meshio.read(out)
    assert sum(len(block) for block in mesh.cell_data["topography"]) == 2
