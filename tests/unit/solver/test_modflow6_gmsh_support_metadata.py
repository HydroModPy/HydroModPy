from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from hydromodpy.spatial.mesh.gmsh_grid import build_gmsh_support_metadata

from ._test_modflow6_boundary_conditions_builders import _build_unstructured_runtime


def test_build_gmsh_support_metadata_from_bundle_like_payload() -> None:
    bundle = SimpleNamespace(
        bundle_dir=".",
        mesh_path="mesh_2d.msh",
        nodes=(
            SimpleNamespace(node_id=0, x=0.0, y=0.0),
            SimpleNamespace(node_id=1, x=1.0, y=0.0),
            SimpleNamespace(node_id=2, x=1.0, y=1.0),
            SimpleNamespace(node_id=3, x=0.0, y=1.0),
        ),
        cells=(
            SimpleNamespace(
                cell_id=0,
                node_indices=(0, 1, 2),
                centroid_x=2.0 / 3.0,
                centroid_y=1.0 / 3.0,
                z_top_mean=30.0,
                z_bottom_mean=10.0,
            ),
            SimpleNamespace(
                cell_id=1,
                node_indices=(0, 2, 3),
                centroid_x=1.0 / 3.0,
                centroid_y=2.0 / 3.0,
                z_top_mean=40.0,
                z_bottom_mean=20.0,
            ),
        ),
        edges=(
            SimpleNamespace(
                edge_id=0,
                node_a=0,
                node_b=1,
                cell_a=0,
                cell_b=None,
                edge_kind="boundary",
                is_river=False,
                geology_a_key="",
                geology_b_key="",
            ),
            SimpleNamespace(
                edge_id=1,
                node_a=1,
                node_b=2,
                cell_a=0,
                cell_b=None,
                edge_kind="boundary",
                is_river=False,
                geology_a_key="",
                geology_b_key="",
            ),
            SimpleNamespace(
                edge_id=2,
                node_a=2,
                node_b=3,
                cell_a=1,
                cell_b=None,
                edge_kind="boundary",
                is_river=False,
                geology_a_key="",
                geology_b_key="",
            ),
            SimpleNamespace(
                edge_id=3,
                node_a=3,
                node_b=0,
                cell_a=1,
                cell_b=None,
                edge_kind="boundary",
                is_river=False,
                geology_a_key="",
                geology_b_key="",
            ),
            SimpleNamespace(
                edge_id=4,
                node_a=0,
                node_b=2,
                cell_a=0,
                cell_b=1,
                edge_kind="internal",
                is_river=False,
                geology_a_key="",
                geology_b_key="",
            ),
        ),
    )

    support = build_gmsh_support_metadata(bundle)

    assert support is not None
    assert support.locate_cell_index_for_point(0.75, 0.25) == 0
    assert support.boundary_cell_indices_for_side("west_side").tolist() == [1]
    np.testing.assert_allclose(support.cell_z_top_m, np.asarray([30.0, 40.0], dtype=float))
    np.testing.assert_allclose(support.cell_z_bottom_m, np.asarray([10.0, 20.0], dtype=float))


def test_gmsh_support_metadata_collects_cells_from_internal_river_edge() -> None:
    _, support = _build_unstructured_runtime(river_internal_edge=True)

    assert support.river_cell_indices().tolist() == [0, 1]


def test_gmsh_support_metadata_resolves_cells_from_explicit_label() -> None:
    _, support = _build_unstructured_runtime(boundary_labels_by_edge_id={1: "east_custom"})

    assert support.cell_indices_for_label("east_custom").tolist() == [0]
