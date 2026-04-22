from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.utils.mesh.gmsh_grid import (
    ExtrudedPrismMesh3D,
    GmshPlanarMesh2D,
    discretize_fieldparam_on_extruded_mesh,
)
from hydromodpy.spatial.field.cases.square.field_spatial_square import FieldSquare
from hydromodpy.spatial.field.core.field_param import FieldParam


def _build_planar_triangles() -> GmshPlanarMesh2D:
    return GmshPlanarMesh2D(
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


def test_discretize_fieldparam_on_extruded_mesh_homogeneous_exponential():
    mesh_3d = ExtrudedPrismMesh3D.from_layer_thicknesses(
        _build_planar_triangles(),
        top_z=0.0,
        layer_thicknesses=[10.0, 10.0, 10.0],
    )
    field_param = FieldParam(
        identifier="K",
        kind="homogeneous",
        value=10.0,
        vertical_profile={"mode": "exponential", "characteristic_depth": 10.0},
    )

    result = discretize_fieldparam_on_extruded_mesh(
        field_param=field_param,
        mesh_3d=mesh_3d,
    )

    assert result.values_2d.shape == (2,)
    assert result.values_3d.shape == (3, 2)
    assert np.allclose(result.values_2d, np.array([10.0, 10.0], dtype=float))

    expected_depths = np.array(
        [
            [5.0, 5.0],
            [15.0, 15.0],
            [25.0, 25.0],
        ],
        dtype=float,
    )
    expected_values = 10.0 * np.exp(-expected_depths / 10.0)
    assert np.allclose(result.prism_center_depths, expected_depths)
    assert np.allclose(result.values_3d, expected_values)


def test_discretize_fieldparam_on_extruded_mesh_heterogeneous_matches_planar_reference():
    planar_mesh = _build_planar_triangles()
    mesh_3d = ExtrudedPrismMesh3D.from_layer_thicknesses(
        planar_mesh,
        top_z=0.0,
        layer_thicknesses=[5.0, 5.0],
    )
    support_field = FieldSquare(
        line="diag_main",
        zone1_side="positive",
        identifier="field_square",
        zone1_name="granite",
        zone2_name="micaschists",
    )
    field_param = FieldParam(
        identifier="K",
        kind="heterogeneous",
        values_by_key={"granite": 10.0, "micaschists": 2.0},
        field_spatial_id="field_square",
    )

    result = discretize_fieldparam_on_extruded_mesh(
        support_field=support_field,
        field_param=field_param,
        mesh_3d=mesh_3d,
    )

    assert result.field_discretization is not None
    assert result.values_2d.shape == (2,)
    assert result.values_3d.shape == (2, 2)
    assert set(np.round(result.values_2d, 12).tolist()) == {2.0, 10.0}
    assert np.allclose(result.values_3d[0], result.values_2d)
    assert np.allclose(result.values_3d[1], result.values_2d)
    assert np.allclose(result.prism_center_depths, np.array([[2.5, 2.5], [7.5, 7.5]], dtype=float))


def test_discretize_fieldparam_on_extruded_mesh_rejects_spatial_id_mismatch():
    mesh_3d = ExtrudedPrismMesh3D.from_layer_thicknesses(
        _build_planar_triangles(),
        top_z=0.0,
        layer_thicknesses=[5.0],
    )
    support_field = FieldSquare(
        line="diag_main",
        zone1_side="positive",
        identifier="field_square",
        zone1_name="granite",
        zone2_name="micaschists",
    )
    field_param = FieldParam(
        identifier="K",
        kind="heterogeneous",
        values_by_key={"granite": 10.0, "micaschists": 2.0},
        field_spatial_id="another_field",
    )

    with pytest.raises(ValueError, match="field_param.field_spatial_id"):
        _ = discretize_fieldparam_on_extruded_mesh(
            support_field=support_field,
            field_param=field_param,
            mesh_3d=mesh_3d,
            strict_field_spatial_id_match=True,
        )


def test_discretize_fieldparam_on_extruded_mesh_requires_support_field_name():
    planar_mesh = _build_planar_triangles()
    mesh_3d = ExtrudedPrismMesh3D.from_layer_thicknesses(
        planar_mesh,
        top_z=0.0,
        layer_thicknesses=[5.0],
    )
    support_field = FieldSquare(
        line="diag_main",
        zone1_side="positive",
        identifier="field_square",
        zone1_name="granite",
        zone2_name="micaschists",
    )
    field_param = FieldParam(
        identifier="K",
        kind="heterogeneous",
        values_by_key={"granite": 10.0, "micaschists": 2.0},
        field_spatial_id="field_square",
    )

    result = discretize_fieldparam_on_extruded_mesh(
        support_field=support_field,
        field_param=field_param,
        mesh_3d=mesh_3d,
    )

    assert result.values_3d.shape == (1, 2)
