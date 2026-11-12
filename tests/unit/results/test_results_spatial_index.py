"""Tests for results/spatial_index.py - point-in-cell."""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from hydromodpy.results.spatial_index import point_in_cell


class TestPointInCellTriangles:
    r"""Simple triangular mesh:

    3---4
    |\ /|
    | 2  |
    |/ \|
    0---1

    Triangles: (0,1,2), (1,4,2), (2,4,3), (0,2,3)
    """

    @pytest.fixture
    def tri_mesh(self):
        vertices = np.array(
            [
                [0.0, 0.0],
                [2.0, 0.0],
                [1.0, 1.0],
                [0.0, 2.0],
                [2.0, 2.0],
            ]
        )
        connectivity = np.array(
            [
                [0, 1, 2],
                [1, 4, 2],
                [2, 4, 3],
                [0, 2, 3],
            ],
            dtype="int32",
        )
        return vertices, connectivity

    def test_point_outside(self, tri_mesh):
        vertices, conn = tri_mesh
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = point_in_cell(vertices, conn, {"OUT": (5.0, 5.0)})
            assert result["OUT"] is None
            assert len(w) == 1
            assert "outside the mesh" in str(w[0].message)


class TestPointInCellMixed:
    """Mixed tri/quad mesh with padding -1."""
