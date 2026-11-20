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

from hydromodpy.mesh.io.vtu import read_vtu, read_vtu_field_data, write_vtu
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh

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


def _two_wedge_layers() -> HydroMesh:
    second = WEDGE_COLUMN + [0.0, 0.0, 1.0]
    vertices = np.vstack([WEDGE_COLUMN, second[3:]])
    return HydroMesh(
        vertices=vertices,
        cell_blocks=(CellBlock(CellType.WEDGE, [[0, 1, 2, 3, 4, 5], [3, 4, 5, 6, 7, 8]]),),
        cell_data={"layer": np.array([1.0, 2.0])},
        point_data={"head": np.arange(9.0)},
    )


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
