"""Tests for HydroMesh adapters."""

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh


class TestFieldMeshAdapter:
    def test_from_gmsh_planar(self) -> None:
        from hydromodpy.spatial.mesh.adapters.field_mesh_adapter import from_gmsh_planar

        planar = SimpleNamespace(
            points_xy=np.array([[0, 0], [1, 0], [0.5, 1]], dtype=float),
            connectivity=np.array([[0, 1, 2]], dtype=int),
            cell_type="triangle",
        )
        mesh = from_gmsh_planar(planar)
        assert mesh.ndim == 2
        assert mesh.n_cells == 1
        assert mesh.single_cell_type is CellType.TRIANGLE

    def test_from_extruded_prism(self) -> None:
        from hydromodpy.spatial.mesh.adapters.field_mesh_adapter import from_extruded_prism

        # 1 triangle extruded into 1 wedge
        extruded = SimpleNamespace(
            points_xyz=np.array([
                [0, 0, 1], [1, 0, 1], [0.5, 1, 1],
                [0, 0, 0], [1, 0, 0], [0.5, 1, 0],
            ], dtype=float),
            prism_connectivity=np.array([[0, 1, 2, 3, 4, 5]], dtype=int),
            cell_type_2d="triangle",
            layer_indices=np.array([0], dtype=int),
            source_cell_indices=np.array([0], dtype=int),
            point_layer_indices=np.array([0, 0, 0, 1, 1, 1], dtype=int),
            point_base_indices=np.array([0, 1, 2, 0, 1, 2], dtype=int),
        )
        mesh = from_extruded_prism(extruded)
        assert mesh.ndim == 3
        assert mesh.n_cells == 1
        assert mesh.single_cell_type is CellType.WEDGE
        assert "layer_index" in mesh.cell_data
        assert "base_index" in mesh.point_data

    def test_from_field_mesh_structured(self) -> None:
        from hydromodpy.spatial.mesh.adapters.field_mesh_adapter import from_field_mesh
        from hydromodpy.spatial.field.meshes import StructuredFieldMesh

        x, y = np.meshgrid([0, 1, 2], [0, 1])
        fm = StructuredFieldMesh(x_plot=x, y_plot=y)
        mesh = from_field_mesh(fm)
        assert mesh.is_structured
        assert mesh.structured_shape == (1, 2)
        assert mesh.n_cells == 2


class TestFlopyAdapter:
    def test_from_flopy_structured_via_delr_delc(self) -> None:
        from hydromodpy.spatial.mesh.adapters.flopy_adapter import from_flopy_structured

        sgrid = SimpleNamespace(
            delr=np.array([100.0, 100.0]),
            delc=np.array([50.0, 50.0, 50.0]),
            xoffset=0.0,
            yoffset=0.0,
            nrow=3,
            ncol=2,
        )
        mesh = from_flopy_structured(sgrid)
        assert mesh.is_structured
        assert mesh.structured_shape == (3, 2)
        assert mesh.n_cells == 6
        assert mesh.single_cell_type is CellType.QUADRILATERAL

    def test_to_flopy_disv_args(self) -> None:
        from hydromodpy.spatial.mesh.adapters.flopy_adapter import to_flopy_disv_args

        verts = np.array([[0, 0], [1, 0], [0.5, 1]], dtype=float)
        mesh = HydroMesh(
            vertices=verts,
            cell_blocks=(CellBlock(CellType.TRIANGLE, np.array([[0, 1, 2]])),),
        )
        result = to_flopy_disv_args(mesh, top=10.0, botm=np.array([[5.0]]))
        assert result["nvert"] == 3
        assert result["ncpl"] == 1
        assert len(result["cell2d"]) == 1
        assert len(result["vertices"]) == 3

    def test_to_flopy_disv_rejects_3d(self) -> None:
        from hydromodpy.spatial.mesh.adapters.flopy_adapter import to_flopy_disv_args

        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0],
                          [0, 0, 1], [1, 0, 1], [0, 1, 1]], dtype=float)
        mesh = HydroMesh(
            vertices=verts,
            cell_blocks=(CellBlock(CellType.WEDGE, np.array([[0, 1, 2, 3, 4, 5]])),),
        )
        with pytest.raises(ValueError, match="2D mesh"):
            to_flopy_disv_args(mesh, top=10.0, botm=np.array([[5.0]]))


class TestMeshioAdapter:
    def test_roundtrip(self) -> None:
        meshio = pytest.importorskip("meshio")
        from hydromodpy.spatial.mesh.adapters.meshio_adapter import from_meshio, to_meshio

        verts = np.array([[0, 0], [1, 0], [0.5, 1], [1.5, 1]], dtype=float)
        conn = np.array([[0, 1, 2], [1, 3, 2]], dtype=int)
        original = HydroMesh(
            vertices=verts,
            cell_blocks=(CellBlock(CellType.TRIANGLE, conn),),
            cell_data={"k": np.array([1.0, 2.0])},
        )
        meshio_mesh = to_meshio(original)
        recovered = from_meshio(meshio_mesh)

        assert recovered.n_cells == 2
        assert recovered.n_nodes == 4
        np.testing.assert_array_almost_equal(
            recovered.vertices[:, :2], verts
        )
        np.testing.assert_array_almost_equal(
            recovered.cell_data["k"], [1.0, 2.0]
        )
