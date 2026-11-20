from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from hydromodpy.solver.modflow6.extractors.flow import Modflow6OutputAdapter


def _grid_file(verts: np.ndarray, closed_rings: list[list[int]]) -> SimpleNamespace:
    return SimpleNamespace(
        verts=verts,
        iavert=np.concatenate([[0], np.cumsum([len(r) for r in closed_rings])]),
        javert=np.concatenate(closed_rings),
    )


def test_modflow6_output_adapter_builds_ugrid_geometry_from_disv_grb_vertices() -> None:
    fake_grid = _grid_file(
        np.array(
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
        [[0, 1, 4, 3, 0], [1, 2, 5, 4, 1]],
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
