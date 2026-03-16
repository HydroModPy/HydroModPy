from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.utils.mesh.gmsh_grid import (
    ExtrudedPrismMesh3D,
    GmshPlanarMesh2D,
    add_clip_plane,
    add_layer_slice,
    add_threshold,
    add_vertical_exaggeration,
    attach_extruded_values,
    build_pyvista_grid,
    build_pyvista_grid_with_values,
    extract_prism_pick_info,
    extract_source_column_grid,
    show_interactive_mesh_3d,
    show_interactive_values_3d,
)

try:
    import pyvista as pv  # noqa: F401
except (ImportError, OSError) as exc:
    pytest.skip(f"could not import 'pyvista': {exc}", allow_module_level=True)


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
        layer_thicknesses=[4.0, 6.0],
    )
    values = np.array([[12.0, 18.0], [9.0, 15.0]], dtype=float)
    depths = np.array([[2.0, 2.0], [7.0, 7.0]], dtype=float)
    mesh_with_values = attach_extruded_values(
        mesh_3d,
        values,
        label="K_3d",
        prism_center_depths=depths,
    )
    return mesh_3d, mesh_with_values


def test_build_pyvista_grid_preserves_geometry_and_metadata():
    mesh_3d, mesh_with_values = _build_mesh_with_values()

    grid = build_pyvista_grid(mesh_3d)
    values_grid = build_pyvista_grid_with_values(mesh_with_values)

    assert grid.n_cells == mesh_3d.n_prisms
    assert grid.n_points == mesh_3d.n_nodes
    assert set(grid.cell_data.keys()) >= {"layer_index", "source_cell_index"}
    assert set(grid.point_data.keys()) >= {"point_layer_index", "point_base_index"}
    assert set(values_grid.cell_data.keys()) >= {
        "field_param_value",
        "prism_center_depth",
        "layer_index",
        "source_cell_index",
    }


def test_vertical_exaggeration_and_selection_helpers():
    _, mesh_with_values = _build_mesh_with_values()
    grid = build_pyvista_grid_with_values(mesh_with_values)

    scaled = add_vertical_exaggeration(grid, 2.5)
    assert np.allclose(
        np.asarray(scaled.points)[:, 2], np.asarray(grid.points)[:, 2] * 2.5
    )

    column_grid = extract_source_column_grid(mesh_with_values, 1)
    assert column_grid.n_cells == mesh_with_values.n_layers

    pick_info = extract_prism_pick_info(mesh_with_values, 2)
    assert pick_info["prism_index"] == 2
    assert pick_info["layer_index"] == 1
    assert pick_info["source_cell_index"] == 0
    assert len(pick_info["vertical_profile"]["values"]) == mesh_with_values.n_layers


def test_plotter_helpers_run_off_screen_without_showing_windows():
    _, mesh_with_values = _build_mesh_with_values()
    grid = build_pyvista_grid_with_values(mesh_with_values)
    plotter = pv.Plotter(off_screen=True)

    try:
        layer_grid, _ = add_layer_slice(
            plotter,
            grid,
            layer_index=0,
            value_name="field_param_value",
            show_edges=True,
        )
        threshold_grid, _ = add_threshold(
            plotter,
            grid,
            scalar_name="field_param_value",
            value_range=(10.0, 20.0),
            show_edges=False,
        )
        clipped_grid, _ = add_clip_plane(
            plotter,
            grid,
            normal="z",
            scalar_name="field_param_value",
            show_edges=False,
        )
    finally:
        plotter.close()

    assert layer_grid.n_cells == mesh_with_values.n_cells_2d
    assert 0 < threshold_grid.n_cells <= grid.n_cells
    assert 0 < clipped_grid.n_cells <= grid.n_cells


def test_interactive_viewer_entry_points_work_in_off_screen_mode():
    mesh_3d, mesh_with_values = _build_mesh_with_values()

    mesh_result = show_interactive_mesh_3d(
        mesh_3d,
        show=False,
        off_screen=True,
        vertical_exaggeration=1.5,
    )
    values_result = show_interactive_values_3d(
        mesh_with_values,
        show=False,
        off_screen=True,
        threshold_range=(10.0, 20.0),
        highlight_source_cell_index=1,
    )

    try:
        assert mesh_result["display_grid"].n_cells == mesh_3d.n_prisms
        assert values_result["display_grid"].n_cells > 0
        assert values_result["selection"]["source_cell_index"] == 1
        assert (
            len(values_result["selection"]["vertical_profile"]["values"])
            == mesh_with_values.n_layers
        )
    finally:
        mesh_result["plotter"].close()
        values_result["plotter"].close()
