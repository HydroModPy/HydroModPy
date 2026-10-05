"""``Descent.basin`` is exactly the set of cells whose receiver chain passes the outlet."""

from __future__ import annotations

import numpy as np
import pytest

from tests.unit.core._descent_meshes import grid_descent

N = 15


def _chain_passes(receiver: np.ndarray, start: int, outlet: int) -> bool:
    cell = start
    while cell >= 0:
        if cell == outlet:
            return True
        cell = int(receiver[cell])
    return False


@pytest.mark.parametrize("seed", [3, 11])
def test_the_basin_matches_a_walk_of_every_chain(seed: int) -> None:
    top = np.random.default_rng(seed).uniform(0.0, 30.0, (N, N))
    descent = grid_descent(top)
    accumulated = np.zeros(N * N, dtype=int)
    for start in range(N * N):
        cell = start
        while cell >= 0:
            accumulated[cell] += 1
            cell = int(descent.receiver[cell])
    outlet = int(np.argmax(accumulated))

    basin = descent.basin(outlet)

    expected = np.array([_chain_passes(descent.receiver, c, outlet) for c in range(N * N)])
    assert np.array_equal(basin, expected)
    assert basin[outlet]
    assert basin.sum() > 1


def test_an_off_graph_outlet_is_refused() -> None:
    routable = np.ones(N * N, dtype=bool)
    routable[0] = False
    descent = grid_descent(np.zeros((N, N)), routable=routable)

    with pytest.raises(ValueError, match="off the descended graph"):
        descent.basin(0)
