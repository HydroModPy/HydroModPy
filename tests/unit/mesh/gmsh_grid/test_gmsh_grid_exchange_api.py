from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.spatial.mesh.gmsh_grid import (
    ExtrudedPrismMesh3D,
    GmshPlanarMesh2D,
    attach_extruded_values,
    load_extruded_mesh,
    load_extruded_mesh_values,
    load_planar_mesh,
    save_extruded_mesh,
    save_extruded_mesh_values,
    save_extruded_values_npy,
    save_extruded_values_summary,
    save_planar_mesh,
)
from hydromodpy.spatial.mesh.gmsh_grid.examples.read_only_example import (
    build_read_only_summary,
)

REFERENCE_PLANAR_MSH = (
    Path(__file__).resolve().parents[4]
    / "hydromodpy"
    / "spatial"
    / "mesh"
    / "gmsh_grid"
    / "cases"
    / "reference_2d_geology_base"
    / "data"
    / "mesh"
    / "reference_triangles.msh"
)
REFERENCE_VALUES_VTU = (
    Path(__file__).resolve().parents[4]
    / "hydromodpy"
    / "spatial"
    / "mesh"
    / "gmsh_grid"
    / "cases"
    / "reference_3d_fieldparam"
    / "outputs"
    / "reference_3d_postprocess.vtu"
)


def _build_small_planar_mesh() -> GmshPlanarMesh2D:
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


def test_exchange_api_can_read_reference_assets():
    pytest.importorskip("meshio")

    planar_mesh = load_planar_mesh(REFERENCE_PLANAR_MSH)
    extruded_mesh = load_extruded_mesh(REFERENCE_VALUES_VTU)
    mesh_with_values = load_extruded_mesh_values(REFERENCE_VALUES_VTU)

    assert planar_mesh.n_cells > 0
    assert extruded_mesh.n_layers > 0
    assert mesh_with_values.n_cells_3d == extruded_mesh.n_prisms
    assert np.asarray(mesh_with_values.values_3d, dtype=float).shape[0] == extruded_mesh.n_layers


def test_exchange_api_roundtrip_with_meshio_available(tmp_path):
    pytest.importorskip("meshio")

    planar_mesh = _build_small_planar_mesh()
    mesh_3d = ExtrudedPrismMesh3D.from_layer_thicknesses(
        planar_mesh,
        top_z=0.0,
        layer_thicknesses=[3.0, 5.0],
    )
    mesh_with_values = attach_extruded_values(
        mesh_3d,
        np.array([[10.0, 20.0], [8.0, 16.0]], dtype=float),
        label="K_3d",
        prism_center_depths=np.array([[1.5, 1.5], [5.5, 5.5]], dtype=float),
    )

    planar_path = tmp_path / "mesh_2d.msh"
    mesh_path = tmp_path / "mesh_3d.vtu"
    values_path = tmp_path / "mesh_values_3d.vtu"
    values_npy_path = tmp_path / "mesh_values_3d.npy"
    summary_json_path = tmp_path / "mesh_values_3d_summary.json"

    save_planar_mesh(planar_mesh, planar_path)
    save_extruded_mesh(mesh_3d, mesh_path)
    save_extruded_mesh_values(mesh_with_values, values_path)
    save_extruded_values_npy(mesh_with_values, values_npy_path)
    save_extruded_values_summary(mesh_with_values, summary_json_path)

    reread_planar = load_planar_mesh(planar_path)
    reread_mesh = load_extruded_mesh(mesh_path)
    reread_values = load_extruded_mesh_values(values_path)

    assert reread_planar.n_cells == planar_mesh.n_cells
    assert reread_mesh.n_prisms == mesh_3d.n_prisms
    assert np.allclose(reread_values.values_3d, mesh_with_values.values_3d)
    assert values_npy_path.exists()
    assert summary_json_path.exists()


def test_read_only_example_builds_summary_from_reference_assets():
    pytest.importorskip("meshio")

    summary = build_read_only_summary(
        planar_mesh_path=REFERENCE_PLANAR_MSH,
        values_vtu_path=REFERENCE_VALUES_VTU,
    )

    assert summary["planar_n_cells"] > 0
    assert summary["extruded_n_layers"] > 0
    assert len(summary["layer_mean_sequence"]) == summary["extruded_n_layers"]
    assert len(summary["center_profile"]) == summary["extruded_n_layers"]
