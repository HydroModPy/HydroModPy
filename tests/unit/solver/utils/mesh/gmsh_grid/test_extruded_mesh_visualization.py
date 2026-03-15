from __future__ import annotations

from pathlib import Path

from matplotlib import pyplot as plt
import numpy as np

from hydromodpy.solver.utils.mesh.gmsh_grid import (
    ExtrudedPrismMesh3D,
    GmshPlanarMesh2D,
    attach_extruded_values,
    build_layer_maps_figure,
    build_source_cell_marker_specs,
    build_vertical_profiles_figure,
    build_visualization_summary,
)


def _build_mesh_with_values():
    planar_mesh = GmshPlanarMesh2D(
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
    mesh_3d = ExtrudedPrismMesh3D.from_layer_thicknesses(
        planar_mesh,
        top_z=0.0,
        layer_thicknesses=[5.0, 10.0, 20.0],
    )
    values_3d = np.array(
        [
            [10.0, 20.0],
            [8.0, 16.0],
            [6.0, 12.0],
        ],
        dtype=float,
    )
    depths = np.array(
        [
            [2.5, 2.5],
            [10.0, 10.0],
            [25.0, 25.0],
        ],
        dtype=float,
    )
    return attach_extruded_values(
        mesh_3d,
        values_3d,
        label="K_3d",
        prism_center_depths=depths,
    )


def test_extruded_mesh_visualization_helpers_build_summary_and_figures():
    mesh_with_values = _build_mesh_with_values()
    marker_specs = build_source_cell_marker_specs(
        mesh_with_values,
        source_cell_indices=[0, 1],
        labels=["A", "B"],
    )

    summary = build_visualization_summary(
        mesh_with_values,
        layer_indices=[0, 2],
        marker_specs=marker_specs,
    )

    assert summary["selected_layers"] == [0, 2]
    assert summary["selected_profiles"][0]["label"] == "A"
    assert summary["selected_profiles"][1]["source_cell_index"] == 1

    layer_fig = build_layer_maps_figure(
        mesh_with_values,
        layer_indices=[0, 2],
        marker_specs=marker_specs,
    )
    profile_fig = build_vertical_profiles_figure(
        mesh_with_values,
        marker_specs=marker_specs,
    )

    assert len(layer_fig.axes) == 3
    assert len(profile_fig.axes) == 2
    plt.close(layer_fig)
    plt.close(profile_fig)

