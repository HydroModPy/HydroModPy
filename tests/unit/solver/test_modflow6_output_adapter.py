from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from hydromodpy.solver.modflow6.extractors.flow import Modflow6OutputAdapter


def test_modflow6_output_adapter_builds_ugrid_geometry_from_disv_grb_vertices() -> None:
    fake_grid = SimpleNamespace(
        verts=np.array(
            [
                [0.0, 0.0],
                [1.0, 0.0],
                [2.0, 0.0],
                [0.0, 1.0],
                [1.0, 1.0],
                [2.0, 1.0],
            ],
            dtype="float64",
        ),
        iverts=[
            [0, 1, 4, 3, 0],
            [1, 2, 5, 4, 1],
        ],
    )

    geometry = Modflow6OutputAdapter._mesh_geometry_from_grid(fake_grid, n_cells=2)

    assert geometry is not None
    vertices, connectivity = geometry
    assert vertices.shape == (6, 3)
    np.testing.assert_array_equal(
        connectivity,
        np.array(
            [
                [0, 1, 4, 3],
                [1, 2, 5, 4],
            ],
            dtype="int32",
        ),
    )


def test_modflow6_output_adapter_pads_mixed_face_connectivity() -> None:
    connectivity = Modflow6OutputAdapter._padded_face_connectivity(
        [
            [0, 1, 2, 0],
            [2, 3, 4, 5, 2],
        ],
        n_cells=2,
    )

    np.testing.assert_array_equal(
        connectivity,
        np.array(
            [
                [0, 1, 2, -1],
                [2, 3, 4, 5],
            ],
            dtype="int32",
        ),
    )


def test_modflow6_output_adapter_infers_structured_shape_from_vertices() -> None:
    x_edges = np.arange(4, dtype="float64")
    y_edges = np.arange(3, dtype="float64")
    xx, yy = np.meshgrid(x_edges, y_edges)
    vertices = np.column_stack([xx.ravel(), yy.ravel(), np.zeros(xx.size)])

    shape = Modflow6OutputAdapter._structured_shape_from_vertices(vertices, n_cells=6)

    assert shape == (2, 3)
