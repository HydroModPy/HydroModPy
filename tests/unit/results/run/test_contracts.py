"""Cell centres (m) and cell areas (m2) of a mesh read back from a run.

Stored face centres win over the mean of the corners. Areas keep their precision far from
the origin, and a face table padded with -1 or NaN gives the same area.
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from hydromodpy.results.run.contracts import Mesh, polygon_areas

CELL = 75.0  # m
LAMBERT_X0, LAMBERT_Y0 = 385_050.0, 6_814_050.0


def lambert_grid(nrow, ncol):
    """A grid of 75 m cells in Lambert-93, row 0 at the north."""
    ys = LAMBERT_Y0 + CELL * (nrow - np.arange(nrow + 1))
    xs = LAMBERT_X0 + CELL * np.arange(ncol + 1)
    vertices = np.array([[x, y, 0.0] for y in ys for x in xs])
    node = np.arange((nrow + 1) * (ncol + 1)).reshape(nrow + 1, ncol + 1)
    faces = np.array(
        [
            [node[i, j], node[i, j + 1], node[i + 1, j + 1], node[i + 1, j]]
            for i in range(nrow)
            for j in range(ncol)
        ],
        dtype=np.int32,
    )
    return vertices, faces


def irregular_mesh():
    """Six cells of 3, 4 and 5 corners, padded with -1."""
    vertices = np.array(
        [
            [0.0, 0.0, 0.0],
            [40.0, 0.0, 0.0],
            [90.0, 10.0, 0.0],
            [140.0, 0.0, 0.0],
            [0.0, 60.0, 0.0],
            [50.0, 70.0, 0.0],
            [100.0, 55.0, 0.0],
            [150.0, 65.0, 0.0],
            [20.0, 120.0, 0.0],
            [80.0, 125.0, 0.0],
            [140.0, 120.0, 0.0],
        ]
    )
    faces = np.array(
        [
            [0, 1, 5, 4, -1],
            [1, 2, 6, 5, -1],
            [2, 3, 7, 6, -1],
            [4, 5, 9, 8, -1],
            [5, 6, 9, -1, -1],
            [6, 7, 10, 9, -1],
        ],
        dtype=np.int32,
    )
    return vertices, faces


def test_stored_face_centres_win_over_the_corner_mean():
    vertices, faces = irregular_mesh()
    mean = Mesh(vertices, faces, np.array([1.0, 0.0])).cell_centers()
    stored_x, stored_y = mean[:, 0] + 1.0, mean[:, 1] - 2.0
    stored = Mesh(
        vertices, faces, np.array([1.0, 0.0]), face_x=stored_x, face_y=stored_y
    ).cell_centers()
    np.testing.assert_array_equal(stored, np.column_stack((stored_x, stored_y)))
    # The mean of a padded row ignores the padding.
    np.testing.assert_allclose(mean[4], vertices[[5, 6, 9], :2].mean(axis=0))


def test_areas_keep_their_precision_far_from_the_origin():
    vertices, faces = lambert_grid(3, 3)
    np.testing.assert_array_equal(polygon_areas(vertices, faces), np.full(9, CELL * CELL))
    irregular_vertices, irregular_faces = irregular_mesh()
    areas = polygon_areas(irregular_vertices, irregular_faces)
    triangle = 0.5 * abs((100 - 50) * (125 - 70) - (80 - 50) * (55 - 70))  # cell 4: corners 5, 6, 9
    assert areas[4] == pytest.approx(triangle)
    assert np.isnan(polygon_areas(vertices, np.array([[0, 1, -1, -1]]))[0])


def test_a_nan_padded_face_table_gives_the_areas_of_its_integer_twin():
    vertices, faces = lambert_grid(2, 2)
    padded = faces.astype(float)
    padded[0, 3] = np.nan

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        areas = polygon_areas(vertices, padded)

    twin = faces.copy()
    twin[0, 3] = -1
    np.testing.assert_array_equal(areas, polygon_areas(vertices, twin))
