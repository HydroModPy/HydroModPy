"""A HydroMesh written to a VTU file reads back with its cells and its fields.

A planar mesh reads back planar, a 3D mesh keeps its z, and a Voronoi mesh of
ragged polygons reads back in its cell order. Values of the whole mesh go to the
``FieldData`` of the grid, texts as UTF-8 bytes and numbers as ``Int32``, and read
back as they were given.
"""

from __future__ import annotations

from pathlib import Path

import meshio
import numpy as np
import pytest
from shapely.geometry import box

from hydromodpy.spatial.mesh.engines.voronoi.tessellation import voronoi_planar_mesh
from hydromodpy.spatial.mesh.io.vtu import read_vtu, read_vtu_field_data, write_vtu
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from tests._helpers.mesh_cases import L93_ORIGIN, regular_mesh

WEDGE_COLUMN = np.array(
    [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1]], dtype=float
)


def _triangles() -> HydroMesh:
    verts = np.array([[0, 0], [1, 0], [0.5, 1], [1.5, 1]], dtype=float)
    return HydroMesh(
        vertices=verts,
        cell_blocks=(CellBlock(CellType.TRIANGLE, np.array([[0, 1, 2], [1, 3, 2]])),),
        cell_data={"conductivity": np.array([1e-4, 2e-4])},
    )


def _grid_in_lambert93() -> HydroMesh:
    mesh = regular_mesh(3, 4, dx=25.0, xmin=L93_ORIGIN[0], ymin=L93_ORIGIN[1]).mesh
    return mesh.with_cell_data(k=np.linspace(1e-5, 1e-4, mesh.n_cells))


def _two_wedge_layers() -> HydroMesh:
    second = WEDGE_COLUMN + [0.0, 0.0, 1.0]
    vertices = np.vstack([WEDGE_COLUMN, second[3:]])
    return HydroMesh(
        vertices=vertices,
        cell_blocks=(CellBlock(CellType.WEDGE, [[0, 1, 2, 3, 4, 5], [3, 4, 5, 6, 7, 8]]),),
        cell_data={"layer": np.array([1.0, 2.0])},
        point_data={"head": np.arange(9.0)},
    )


@pytest.mark.parametrize(
    "build", [_triangles, _grid_in_lambert93, _two_wedge_layers], ids=["triangles", "grid", "3d"]
)
def test_a_mesh_written_as_vtu_reads_back_with_its_cells_and_fields(tmp_path: Path, build) -> None:
    original = build()

    path = write_vtu(tmp_path / "mesh.vtu", original)
    recovered = read_vtu(path)

    assert path == (tmp_path / "mesh.vtu").resolve()
    assert recovered.cell_types == original.cell_types
    np.testing.assert_array_equal(recovered.flat_connectivity, original.flat_connectivity)
    np.testing.assert_array_equal(recovered.vertices[:, : original.ndim], original.vertices)
    for name, values in original.cell_data.items():
        np.testing.assert_array_equal(recovered.cell_data[name], values)
    for name, values in original.point_data.items():
        np.testing.assert_array_equal(recovered.point_data[name], values)


def test_a_planar_mesh_written_as_vtu_reads_back_planar(tmp_path: Path) -> None:
    recovered = read_vtu(write_vtu(tmp_path / "mesh.vtu", _triangles()))

    assert recovered.ndim == 2


def test_a_3d_mesh_written_as_vtu_keeps_its_z(tmp_path: Path) -> None:
    recovered = read_vtu(write_vtu(tmp_path / "mesh.vtu", _two_wedge_layers()))

    assert recovered.ndim == 3
    np.testing.assert_array_equal(recovered.vertices, _two_wedge_layers().vertices)


def test_two_triangles_written_as_vtu_read_back(tmp_path: Path) -> None:
    hydro_mesh = HydroMesh(
        vertices=np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]),
        cell_blocks=(CellBlock(CellType.TRIANGLE, np.array([[0, 1, 2], [0, 2, 3]], dtype=int)),),
    )

    reread = read_vtu(write_vtu(tmp_path / "mesh.vtu", hydro_mesh))

    assert reread.n_cells == hydro_mesh.n_cells
    assert np.allclose(reread.vertices[:, :2], hydro_mesh.vertices[:, :2])


def test_a_voronoi_mesh_written_as_vtu_reads_back_in_its_cell_order(tmp_path: Path) -> None:
    seeds = np.random.default_rng(5).uniform(0.0, 100.0, (60, 2))
    original = voronoi_planar_mesh(seeds, box(0.0, 0.0, 100.0, 100.0))
    original = original.with_cell_data(k=np.arange(original.n_cells, dtype=float))
    assert len(set((original.flat_connectivity >= 0).sum(axis=1).tolist())) > 1

    recovered = read_vtu(write_vtu(tmp_path / "voronoi.vtu", original))

    assert recovered.cell_types == (CellType.POLYGON,)
    assert [list(c) for c in recovered.flat_connectivity] == [
        list(c) for c in original.flat_connectivity
    ]
    np.testing.assert_array_equal(recovered.vertices, original.vertices)
    np.testing.assert_array_equal(recovered.cell_data["k"], original.cell_data["k"])


def test_the_field_data_reads_back_as_it_was_given(tmp_path: Path) -> None:
    values = {"sim_id": "a-run", "epsg_code": 2154, "crs_wkt": 'PROJCRS["é"]'}

    path = write_vtu(tmp_path / "mesh.vtu", _triangles(), field_data={**values, "empty": ""})

    assert read_vtu_field_data(path) == values
    assert list(meshio.read(path).field_data) == list(values)
    assert meshio.read(path).field_data["sim_id"].dtype == np.uint8
    assert meshio.read(path).field_data["epsg_code"].dtype == np.int32


@pytest.mark.parametrize("field_data", [None, {}, {"empty": ""}], ids=["none", "empty", "no text"])
def test_a_mesh_written_without_field_data_has_none(tmp_path: Path, field_data) -> None:
    path = write_vtu(tmp_path / "mesh.vtu", _triangles(), field_data=field_data)

    assert read_vtu_field_data(path) == {}
    assert "FieldData" not in path.read_text(encoding="utf-8")


def test_a_field_data_array_of_another_kind_reads_as_an_array(tmp_path: Path) -> None:
    path = write_vtu(tmp_path / "mesh.vtu", _triangles(), field_data={"sim_id": "a-run"})
    text = path.read_text(encoding="utf-8").replace(
        "</FieldData>",
        '<DataArray type="Float64" Name="origin" NumberOfTuples="2" format="ascii">'
        "1.5 2.5</DataArray></FieldData>",
    )
    path.write_text(text, encoding="utf-8")

    values = read_vtu_field_data(path)

    assert values["sim_id"] == "a-run"
    np.testing.assert_array_equal(values["origin"], [1.5, 2.5])
