"""UGRID face-field rendering, one value per mesh face drawn as a polygon."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.display.maps.ugrid import render_face_field


def mesh_run(connectivity: np.ndarray) -> SimpleNamespace:
    """Two faces on six vertices, a square and its right neighbor."""
    vertices = [
        [0.0, 0.0, 10.0],
        [1.0, 0.0, 11.0],
        [1.0, 1.0, 12.0],
        [0.0, 1.0, 13.0],
        [2.0, 0.0, 14.0],
        [2.0, 1.0, 15.0],
    ]
    mesh = SimpleNamespace(
        vertices=np.asarray(vertices),
        face_node_connectivity=connectivity,
    )
    return SimpleNamespace(mesh=mesh)


def test_float_nan_padding_is_ignored(mpl) -> None:
    sim = mesh_run(np.asarray([[0.0, 1.0, 2.0, np.nan], [0.0, 2.0, 3.0, np.nan]]))
    fig, ax = mpl.subplots()

    collection = render_face_field(ax, sim, np.asarray([1.0, 2.0]))

    polygons = [path.vertices[:-1] for path in collection.get_paths()]
    assert [polygon.shape[0] for polygon in polygons] == [3, 3]
    assert np.allclose(polygons[0], [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]])


def test_value_count_mismatch_is_refused(mpl) -> None:
    sim = mesh_run(np.asarray([[0, 1, 2, 3], [1, 4, 5, 2]], dtype=int))
    fig, ax = mpl.subplots()

    with pytest.raises(ValueError, match="face field has 1 values but mesh has 2 faces"):
        render_face_field(ax, sim, np.asarray([10.0]))
