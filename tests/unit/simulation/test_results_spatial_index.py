"""Tests for simulation/results/spatial_index.py — point-in-cell."""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from hydromodpy.results.spatial_index import point_in_cell


class TestPointInCellTriangles:
    """Simple triangular mesh:

    3---4
    |\ /|
    | 2  |
    |/ \|
    0---1

    Triangles: (0,1,2), (1,4,2), (2,4,3), (0,2,3)
    """

    @pytest.fixture
    def tri_mesh(self):
        vertices = np.array([
            [0.0, 0.0],
            [2.0, 0.0],
            [1.0, 1.0],
            [0.0, 2.0],
            [2.0, 2.0],
        ])
        connectivity = np.array([
            [0, 1, 2],
            [1, 4, 2],
            [2, 4, 3],
            [0, 2, 3],
        ], dtype="int32")
        return vertices, connectivity

    def test_point_inside(self, tri_mesh):
        vertices, conn = tri_mesh
        result = point_in_cell(vertices, conn, {"P1": (0.5, 0.3)})
        assert result["P1"] == 0  # bottom-left triangle

    def test_point_in_different_cell(self, tri_mesh):
        vertices, conn = tri_mesh
        # Triangle 1: vertices (2,0), (2,2), (1,1) — centroid ~(1.67, 1.0)
        result = point_in_cell(vertices, conn, {"P2": (1.7, 0.8)})
        assert result["P2"] == 1

    def test_point_outside(self, tri_mesh):
        vertices, conn = tri_mesh
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = point_in_cell(vertices, conn, {"OUT": (5.0, 5.0)})
            assert result["OUT"] is None
            assert len(w) == 1
            assert "outside the mesh" in str(w[0].message)

    def test_multiple_points(self, tri_mesh):
        vertices, conn = tri_mesh
        pts = {"A": (0.5, 0.3), "B": (1.5, 0.3), "C": (10.0, 10.0)}
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = point_in_cell(vertices, conn, pts)
        assert result["A"] is not None
        assert result["B"] is not None
        assert result["C"] is None


class TestPointInCellMixed:
    """Mixed tri/quad mesh with padding -1."""

    @pytest.fixture
    def mixed_mesh(self):
        vertices = np.array([
            [0.0, 0.0],  # 0
            [1.0, 0.0],  # 1
            [2.0, 0.0],  # 2
            [0.5, 1.0],  # 3
            [1.0, 1.0],  # 4
            [2.0, 1.0],  # 5
        ])
        # cell 0: triangle (0,1,3), cell 1: quad (1,2,5,4)
        connectivity = np.array([
            [0, 1, 3, -1],
            [1, 2, 5, 4],
        ], dtype="int32")
        return vertices, connectivity

    def test_point_in_triangle(self, mixed_mesh):
        vertices, conn = mixed_mesh
        result = point_in_cell(vertices, conn, {"T": (0.4, 0.3)})
        assert result["T"] == 0

    def test_point_in_quad(self, mixed_mesh):
        vertices, conn = mixed_mesh
        result = point_in_cell(vertices, conn, {"Q": (1.5, 0.5)})
        assert result["Q"] == 1
