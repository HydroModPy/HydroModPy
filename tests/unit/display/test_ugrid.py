"""Unit tests for UGRID face-field rendering."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.display.ugrid import render_face_field


def _mesh_run(connectivity: np.ndarray) -> SimpleNamespace:
    mesh = SimpleNamespace(
        vertices=np.asarray(
            [
                [0.0, 0.0, 10.0],
                [1.0, 0.0, 11.0],
                [1.0, 1.0, 12.0],
                [0.0, 1.0, 13.0],
                [2.0, 0.0, 14.0],
                [2.0, 1.0, 15.0],
            ]
        ),
        face_node_connectivity=connectivity,
    )
    return SimpleNamespace(mesh=mesh)


def test_render_face_field_ignores_integer_padding_and_labels_colorbar() -> None:
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    sim = _mesh_run(np.asarray([[0, 1, 2, 3], [1, 4, 5, 2]], dtype=int))
    fig, ax = plt.subplots()

    collection = render_face_field(
        ax,
        sim,
        np.asarray([10.0, 20.0]),
        vmin=0.0,
        vmax=30.0,
        cbar_label="Head [m]",
    )

    try:
        assert len(collection.get_paths()) == 2
        assert collection.get_array().tolist() == [10.0, 20.0]
        assert collection.get_clim() == (0.0, 30.0)
        assert fig.axes[-1].get_ylabel() == "Head [m]"
    finally:
        plt.close(fig)


def test_render_face_field_ignores_float_nan_padding() -> None:
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    sim = _mesh_run(np.asarray([[0.0, 1.0, 2.0, np.nan], [0.0, 2.0, 3.0, np.nan]]))
    fig, ax = plt.subplots()

    collection = render_face_field(ax, sim, np.asarray([1.0, 2.0]))

    try:
        polygons = [path.vertices[:-1] for path in collection.get_paths()]
        assert [polygon.shape[0] for polygon in polygons] == [3, 3]
        assert np.allclose(polygons[0], [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]])
    finally:
        plt.close(fig)


def test_render_face_field_rejects_value_count_mismatch() -> None:
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    sim = _mesh_run(np.asarray([[0, 1, 2, 3], [1, 4, 5, 2]], dtype=int))
    fig, ax = plt.subplots()

    try:
        with pytest.raises(ValueError, match="face field has 1 values but mesh has 2 faces"):
            render_face_field(ax, sim, np.asarray([10.0]))
    finally:
        plt.close(fig)
