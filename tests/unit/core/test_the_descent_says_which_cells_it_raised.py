"""D flags the cells it raised, and a model keeps it without its adjacency.

The flow direction map draws the raised cells from that flag: comparing D's
surface with a top that went through a text file would mark cells D never
touched. The adjacency sets are the heavy part of D and nothing reads them
after the build, so the copy a model keeps drops them and nothing else.
"""

from __future__ import annotations

import numpy as np

from tests.unit.core._descent_meshes import grid_descent

N = 9


def _bowl() -> np.ndarray:
    rows, cols = np.meshgrid(np.arange(N), np.arange(N), indexing="ij")
    return 5.0 + (rows - N // 2) ** 2 + (cols - N // 2) ** 2


def test_the_raised_cells_are_those_the_flood_lifted() -> None:
    top = _bowl().reshape(-1)

    descent = grid_descent(_bowl())

    assert descent.raised.dtype == bool
    assert np.array_equal(descent.raised, descent.surface > top)
    assert int(descent.raised.sum()) == descent.n_raised


def test_the_light_descent_drops_only_the_adjacency() -> None:
    descent = grid_descent(_bowl())

    light = descent.without_adjacency()

    assert descent.adjacency is not None
    assert light.adjacency is None
    assert light.metric is descent.metric
    for name in ("surface", "base_level", "constant_head", "raised", "channel", "pinned"):
        assert getattr(light, name) is getattr(descent, name)
    assert np.array_equal(
        light.basin(int(np.argmin(descent.surface))), descent.basin(int(np.argmin(descent.surface)))
    )
