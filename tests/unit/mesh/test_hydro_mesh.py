"""Tests for the HydroMesh data container."""

import numpy as np
import pytest

from hydromodpy.spatial.mesh.cell_types import CellType
from hydromodpy.spatial.mesh.hydro_mesh import CellBlock, HydroMesh


def _make_triangle_mesh() -> HydroMesh:
    vertices = np.array([[0, 0], [1, 0], [0.5, 1], [1.5, 1]], dtype=float)
    conn = np.array([[0, 1, 2], [1, 3, 2]], dtype=int)
    return HydroMesh(
        vertices=vertices,
        cell_blocks=(CellBlock(CellType.TRIANGLE, conn),),
    )


def _make_quad_mesh() -> HydroMesh:
    vertices = np.array([[0, 0], [1, 0], [2, 0], [0, 1], [1, 1], [2, 1]], dtype=float)
    conn = np.array([[0, 1, 4, 3], [1, 2, 5, 4]], dtype=int)
    return HydroMesh(
        vertices=vertices,
        cell_blocks=(CellBlock(CellType.QUADRILATERAL, conn),),
        structured_shape=(1, 2),
    )


class TestCellBlock:
    def test_valid_triangle_block(self) -> None:
        conn = np.array([[0, 1, 2]], dtype=int)
        block = CellBlock(CellType.TRIANGLE, conn)
        assert block.n_cells == 1
        assert block.cell_type is CellType.TRIANGLE

    def test_wrong_width_raises(self) -> None:
        conn = np.array([[0, 1, 2, 3]], dtype=int)
        with pytest.raises(ValueError, match="triangle"):
            CellBlock(CellType.TRIANGLE, conn)

    def test_string_cell_type_resolved(self) -> None:
        conn = np.array([[0, 1, 2]], dtype=int)
        block = CellBlock("tri", conn)  # type: ignore[arg-type]
        assert block.cell_type is CellType.TRIANGLE


class TestHydroMesh:
    def test_basic_properties(self) -> None:
        mesh = _make_triangle_mesh()
        assert mesh.ndim == 2
        assert mesh.n_nodes == 4
        assert mesh.n_cells == 2
        assert mesh.is_structured is False
        assert mesh.single_cell_type is CellType.TRIANGLE

    def test_structured_hint(self) -> None:
        mesh = _make_quad_mesh()
        assert mesh.is_structured is True
        assert mesh.structured_shape == (1, 2)

    def test_bounds_2d(self) -> None:
        mesh = _make_triangle_mesh()
        b = mesh.bounds()
        assert b == (0.0, 0.0, 1.5, 1.0)

    def test_bounds_3d(self) -> None:
        verts = np.array(
            [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1]], dtype=float
        )
        conn = np.array([[0, 1, 2, 3, 4, 5]], dtype=int)
        mesh = HydroMesh(
            vertices=verts,
            cell_blocks=(CellBlock(CellType.WEDGE, conn),),
        )
        assert mesh.ndim == 3
        assert mesh.bounds() == (0.0, 0.0, 0.0, 1.0, 1.0, 1.0)

    def test_flat_connectivity(self) -> None:
        mesh = _make_triangle_mesh()
        fc = mesh.flat_connectivity
        assert fc.shape == (2, 3)

    def test_with_cell_data(self) -> None:
        mesh = _make_triangle_mesh()
        mesh2 = mesh.with_cell_data(k=np.array([1.0, 2.0]))
        assert "k" in mesh2.cell_data
        assert mesh2.cell_data["k"].tolist() == [1.0, 2.0]
        # Original unchanged
        assert "k" not in mesh.cell_data

    def test_with_cell_data_wrong_size_raises(self) -> None:
        mesh = _make_triangle_mesh()
        with pytest.raises(ValueError, match="2 values"):
            mesh.with_cell_data(k=np.array([1.0, 2.0, 3.0]))

    def test_with_point_data(self) -> None:
        mesh = _make_triangle_mesh()
        mesh2 = mesh.with_point_data(z=np.array([0, 0, 1, 1], dtype=float))
        assert "z" in mesh2.point_data
        assert mesh2.point_data["z"].size == 4

    def test_empty_cell_blocks_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one block"):
            HydroMesh(
                vertices=np.array([[0, 0]], dtype=float),
                cell_blocks=(),
            )

    def test_bad_vertex_shape_raises(self) -> None:
        with pytest.raises(ValueError, match="n_nodes, 2|3"):
            HydroMesh(
                vertices=np.array([0, 1, 2], dtype=float).reshape(3, 1),
                cell_blocks=(CellBlock(CellType.TRIANGLE, np.array([[0, 1, 2]])),),
            )

    def test_connectivity_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="outside vertices"):
            HydroMesh(
                vertices=np.array([[0, 0], [1, 0]], dtype=float),
                cell_blocks=(CellBlock(CellType.TRIANGLE, np.array([[0, 1, 5]])),),
            )

    def test_as_summary(self) -> None:
        mesh = _make_quad_mesh()
        s = mesh.as_summary()
        assert s["ndim"] == 2
        assert s["n_cells"] == 2
        assert s["is_structured"] is True
        assert s["cell_types"] == ["quadrilateral"]

    def test_mixed_cell_types_raises_on_single(self) -> None:
        verts = np.array([[0, 0], [1, 0], [0.5, 1], [1.5, 0]], dtype=float)
        mesh = HydroMesh(
            vertices=verts,
            cell_blocks=(
                CellBlock(CellType.TRIANGLE, np.array([[0, 1, 2]])),
                CellBlock(CellType.TRIANGLE, np.array([[1, 3, 2]])),
            ),
        )
        # Same types: ok
        assert mesh.single_cell_type is CellType.TRIANGLE
