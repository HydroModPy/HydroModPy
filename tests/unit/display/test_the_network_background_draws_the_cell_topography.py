"""The network maps colour each cell by its topography, under every solver."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.display.figures.hydrographic_network import plot_topography_background

_VERTS = np.asarray([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [2.0, 0.0], [2.0, 1.0]])
_CONN = np.asarray([[0, 1, 2, 3], [1, 4, 5, 2]], dtype=int)


def _run(*, topography, z_interfaces) -> SimpleNamespace:
    mesh = SimpleNamespace(
        vertices=_VERTS,
        face_node_connectivity=_CONN,
        z_interfaces=np.asarray(z_interfaces, dtype=float),
        topography=None if topography is None else np.asarray(topography, dtype=float),
    )
    return SimpleNamespace(mesh=mesh)


@pytest.fixture
def ax():
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots()
    yield axes
    plt.close(fig)


def test_a_modflow_run_draws_its_topography_not_its_layer_column(ax) -> None:
    # MODFLOW stores z_interfaces as one column of n_layers + 1 values.
    run = _run(topography=[12.0, 10.0], z_interfaces=[12.0, 5.0, -10.0])
    plot_topography_background(ax, run)
    np.testing.assert_allclose(ax.collections[0].get_array(), [12.0, 10.0])


def test_a_run_without_topography_draws_nothing(ax) -> None:
    plot_topography_background(ax, _run(topography=None, z_interfaces=[12.0, -10.0]))
    assert not ax.collections
