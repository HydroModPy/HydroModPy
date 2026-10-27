"""Unit tests for the VTU export: cell blocks on mixed / Voronoi meshes, run metadata."""

from __future__ import annotations

import meshio
import numpy as np
import pytest

from hydromodpy.results.exporters.vtu import _build_meshio_cells, _split_cell_data, export_vtu
from hydromodpy.results.zarr_store import SimulationZarr

# Interleaved valences with a -1 tail pad: tri, pentagon, quad, tri.
# Contiguous slicing (the old bug) would mis-group and mis-assign these.
_CONNECTIVITY = np.array(
    [
        [0, 1, 2, -1, -1],  # face 0: triangle
        [3, 4, 5, 6, 7],  # face 1: pentagon
        [8, 9, 10, 11, -1],  # face 2: quad
        [12, 13, 14, -1, -1],  # face 3: triangle
    ]
)


def test_build_meshio_cells_preserves_valence_without_dropping_nodes():
    cells, cell_indices = _build_meshio_cells(_CONNECTIVITY)
    by_type = {cb.type: (cb, idx) for cb, idx in zip(cells, cell_indices)}

    assert set(by_type) == {"triangle", "quad", "polygon"}

    tri_cb, tri_idx = by_type["triangle"]
    assert tri_cb.data.shape == (2, 3)
    assert list(tri_idx) == [0, 3]

    quad_cb, quad_idx = by_type["quad"]
    assert quad_cb.data.shape == (1, 4)
    assert list(quad_idx) == [2]

    # The pentagon keeps all five nodes instead of being truncated to a quad.
    poly_cb, poly_idx = by_type["polygon"]
    assert poly_cb.data.shape == (1, 5)
    assert list(poly_idx) == [1]
    assert list(poly_cb.data[0]) == [3, 4, 5, 6, 7]


def test_split_cell_data_gathers_by_original_face_index():
    data = np.array([10.0, 11.0, 12.0, 13.0])  # per-face field values
    cells, cell_indices = _build_meshio_cells(_CONNECTIVITY)
    split = _split_cell_data(data, cell_indices)
    by_type = {cb.type: arr for cb, arr in zip(cells, split)}

    # Values follow their faces, not a contiguous block slice.
    assert list(by_type["triangle"]) == [10.0, 13.0]  # faces 0, 3
    assert list(by_type["polygon"]) == [11.0]  # face 1
    assert list(by_type["quad"]) == [12.0]  # face 2


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
