from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.solver.utils.mesh.gmsh_grid import (
    ExtrudedPrismMesh3D,
    ExtrudedPrismMeshWithValues,
    GmshPlanarMesh2D,
    attach_extruded_values,
)


def _build_mesh_3d() -> ExtrudedPrismMesh3D:
    mesh_2d = GmshPlanarMesh2D(
        points_xy=np.array(
            [
                [0.0, 0.0],
                [1.0, 0.0],
                [1.0, 1.0],
                [0.0, 1.0],
            ],
            dtype=float,
        ),
        connectivity=np.array([[0, 1, 2], [0, 2, 3]], dtype=int),
        cell_type="triangle",
    )
    return ExtrudedPrismMesh3D.from_layer_thicknesses(
        mesh_2d,
        top_z=0.0,
        layer_thicknesses=[5.0, 10.0],
    )


def test_attach_extruded_values_supports_layer_and_profile_queries():
    mesh_3d = _build_mesh_3d()
    values_3d = np.array([[10.0, 20.0], [8.0, 16.0]], dtype=float)
    depths = np.array([[2.5, 2.5], [10.0, 10.0]], dtype=float)

    attached = attach_extruded_values(
        mesh_3d,
        values_3d,
        label="K_3d",
        prism_center_depths=depths,
        metadata={"field_param_id": "K"},
    )

    assert isinstance(attached, ExtrudedPrismMeshWithValues)
    assert attached.n_layers == 2
    assert attached.n_cells_2d == 2
    assert attached.n_cells_3d == 4
    assert np.allclose(attached.flat_values, np.array([10.0, 20.0, 8.0, 16.0], dtype=float))

    layer0 = attached.extract_layer(0)
    assert np.allclose(np.asarray(layer0.cell_values, dtype=float).reshape(-1), np.array([10.0, 20.0]))

    profile = attached.extract_vertical_profile(1)
    assert profile["source_cell_index"] == 1
    assert profile["layer_indices"] == [0, 1]
    assert np.allclose(profile["values"], np.array([20.0, 16.0], dtype=float))
    assert np.allclose(profile["depths"], np.array([2.5, 10.0], dtype=float))

    summary = attached.to_summary_dict()
    assert summary["shape_3d"] == [2, 2]
    assert summary["values_signature_head"][:4] == [10.0, 20.0, 8.0, 16.0]
    assert summary["metadata"]["field_param_id"] == "K"


def test_extruded_mesh_values_reject_invalid_shape():
    mesh_3d = _build_mesh_3d()
    with pytest.raises(ValueError, match="one value per prism"):
        _ = attach_extruded_values(mesh_3d, np.array([1.0, 2.0, 3.0], dtype=float))


def test_extruded_mesh_values_vtu_roundtrip_if_meshio_available():
    pytest.importorskip("meshio")

    mesh_3d = _build_mesh_3d()
    attached = attach_extruded_values(
        mesh_3d,
        np.array([[10.0, 20.0], [8.0, 16.0]], dtype=float),
        label="K_3d",
        prism_center_depths=np.array([[2.5, 2.5], [10.0, 10.0]], dtype=float),
    )

    output_dir = Path.cwd() / "scratch_tests" / "extruded_mesh_values" / "runtime"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "values_3d.vtu"
    attached.to_file(path, value_name="K_value", depth_name="depth_center")
    reread = ExtrudedPrismMeshWithValues.from_file(
        path,
        value_name="K_value",
        depth_name="depth_center",
        label="K_3d",
    )

    assert reread.label == "K_3d"
    assert reread.mesh.n_prisms == attached.mesh.n_prisms
    assert np.allclose(reread.values_3d, attached.values_3d)
    assert np.allclose(reread.prism_center_depths, attached.prism_center_depths)
