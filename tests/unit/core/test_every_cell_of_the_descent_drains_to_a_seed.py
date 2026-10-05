"""Every routable cell that is not a seed has a receiver, and no chain cycles.

This is the contract the consumers rely on: the reach rectification turns a -1
into an outlet reach and the drainage mover into a plain drain. On D a -1 only
happens on a seed, on a quad grid and on a mesh without diagonals alike, and
around a hole of non-routable cells, whose rim is a seed too.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.descent import build_descent
from tests.unit.core._descent_meshes import (
    chain_ends_without_cycle,
    grid_descent,
    triangle_mesh,
)

N = 12


def _rough_top(n_cells: int) -> np.ndarray:
    return np.random.default_rng(7).uniform(0.0, 20.0, n_cells)


def _with_a_hole(n_cells: int) -> np.ndarray:
    routable = np.ones(n_cells, dtype=bool)
    routable[n_cells // 2 : n_cells // 2 + 3] = False
    return routable


@pytest.mark.parametrize("routable", [None, "hole"])
def test_on_a_quad_grid(routable: str | None) -> None:
    mask = _with_a_hole(N * N) if routable == "hole" else np.ones(N * N, dtype=bool)

    descent = grid_descent(_rough_top(N * N).reshape(N, N), routable=mask)

    stranded = descent.routable & ~descent.base_level & (descent.receiver < 0)
    assert not np.any(stranded)
    assert chain_ends_without_cycle(descent)
    assert not np.any(descent.routable[~mask])


def test_on_a_triangle_mesh() -> None:
    vertices, connectivity, centroids = triangle_mesh(N, N)
    n_cells = connectivity.shape[0]

    descent = build_descent(
        _rough_top(n_cells),
        connectivity,
        vertices=vertices,
        centroids=centroids,
        routable=_with_a_hole(n_cells),
    )

    stranded = descent.routable & ~descent.base_level & (descent.receiver < 0)
    assert not np.any(stranded)
    assert chain_ends_without_cycle(descent)
