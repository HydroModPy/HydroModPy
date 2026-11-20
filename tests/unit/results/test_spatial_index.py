"""Point-in-cell lookup on a mesh, with its on-disk cache of the answers.

Coordinates are in meters of the mesh CRS. A point outside every cell is
reported as ``None`` with a warning, and that answer is cached too.
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from hydromodpy.results.spatial_index import CellLocator, point_in_cell

# A 2x2 grid of unit squares: cells 0..3, centers at (0.5, 0.5) ... (1.5, 1.5).
GRID_VERTICES = np.array(
    [
        [0.0, 0.0],
        [1.0, 0.0],
        [2.0, 0.0],
        [0.0, 1.0],
        [1.0, 1.0],
        [2.0, 1.0],
        [0.0, 2.0],
        [1.0, 2.0],
        [2.0, 2.0],
    ]
)
GRID_CONNECTIVITY = np.array(
    [[0, 1, 4, 3], [1, 2, 5, 4], [3, 4, 7, 6], [4, 5, 8, 7]], dtype="int32"
)

# Four triangles around the central vertex 2 of a 2 m square.
TRIANGLE_VERTICES = np.array([[0.0, 0.0], [2.0, 0.0], [1.0, 1.0], [0.0, 2.0], [2.0, 2.0]])
TRIANGLE_CONNECTIVITY = np.array([[0, 1, 2], [1, 4, 2], [2, 4, 3], [0, 2, 3]], dtype="int32")


def test_point_in_cell():
    assert point_in_cell(GRID_VERTICES, GRID_CONNECTIVITY, {"p": (0.5, 1.5)}) == {"p": 2}


@pytest.mark.parametrize(
    ("vertices", "connectivity"),
    [
        pytest.param(TRIANGLE_VERTICES, TRIANGLE_CONNECTIVITY, id="triangles"),
        pytest.param(GRID_VERTICES, GRID_CONNECTIVITY, id="squares"),
    ],
)
def test_a_point_outside_warns(vertices, connectivity):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = point_in_cell(vertices, connectivity, {"OUT": (9.0, 9.0)})

    assert result["OUT"] is None
    assert len(caught) == 1
    assert "outside the mesh" in str(caught[0].message)


def test_a_cached_point_never_builds_the_tree(tmp_path):
    warm = CellLocator(
        GRID_VERTICES, GRID_CONNECTIVITY, fingerprint="abc", cache_dir=tmp_path / "c"
    )
    warm.locate({"p": (1.5, 0.5)})
    cold = CellLocator(
        GRID_VERTICES, GRID_CONNECTIVITY, fingerprint="abc", cache_dir=tmp_path / "c"
    )

    assert cold.locate({"p": (1.5, 0.5)}) == {"p": 1}
    assert cold._tree is None


def test_a_point_outside_is_cached_as_outside(tmp_path):
    locator = CellLocator(
        GRID_VERTICES, GRID_CONNECTIVITY, fingerprint="abc", cache_dir=tmp_path / "c"
    )
    assert locator.locate({"p": (9.0, 9.0)}, warn_outside=False) == {"p": None}

    cold = CellLocator(
        GRID_VERTICES, GRID_CONNECTIVITY, fingerprint="abc", cache_dir=tmp_path / "c"
    )
    assert cold.locate({"p": (9.0, 9.0)}, warn_outside=False) == {"p": None}
