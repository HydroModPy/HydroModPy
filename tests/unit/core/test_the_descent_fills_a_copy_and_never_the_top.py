"""D raises an interior pit on its own copy; the model top is left as it was.

The copy is a routing computation (principle P2). The solver, the drain
elevations and the reach tops read the top T, so a descent that wrote its fill
back would change the ground the model is built on.
"""

from __future__ import annotations

import numpy as np

from tests.unit.core._descent_meshes import grid_descent

N = 6
PIT = (3, 3)


def _sloping_top_with_a_pit() -> np.ndarray:
    rows, cols = np.meshgrid(np.arange(N), np.arange(N), indexing="ij")
    top = 10.0 + rows + cols
    top[PIT] = 5.0
    return top


def test_the_pit_is_raised_on_the_copy_only() -> None:
    top = _sloping_top_with_a_pit()
    before = top.copy()

    descent = grid_descent(top)

    pit = PIT[0] * N + PIT[1]
    assert np.array_equal(top, before)
    assert descent.surface[pit] > top[PIT]
    assert descent.n_raised >= 1
    assert descent.max_raise_m > 0.0
    assert descent.receiver[pit] >= 0


def test_the_copy_never_lies_below_the_top() -> None:
    top = _sloping_top_with_a_pit()

    descent = grid_descent(top)

    flat = top.reshape(-1)
    routable = descent.routable
    assert np.all(descent.surface[routable] >= flat[routable])
    assert np.all(np.isnan(descent.surface[~routable]))
