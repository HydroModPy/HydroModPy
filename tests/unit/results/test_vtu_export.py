"""Unit tests for VTU cell-block building on mixed / Voronoi meshes."""

from __future__ import annotations

import numpy as np

from hydromodpy.results.exporters.vtu import _build_meshio_cells, _split_cell_data

# Interleaved valences with a -1 tail pad: tri, pentagon, quad, tri.
# Contiguous slicing (the old bug) would mis-group and mis-assign these.
_CONNECTIVITY = np.array(
    [
        [0, 1, 2, -1, -1],  # face 0: triangle
        [3, 4, 5, 6, 7],  # face 1: pentagon
        [8, 9, 10, 11, -1],  # face 2: quad
        [12, 13, 14, -1, -1],  # face 3: triangle
    ]
)


def test_build_meshio_cells_preserves_valence_without_dropping_nodes():
    cells, cell_indices = _build_meshio_cells(_CONNECTIVITY)
    by_type = {cb.type: (cb, idx) for cb, idx in zip(cells, cell_indices)}

    assert set(by_type) == {"triangle", "quad", "polygon"}

    tri_cb, tri_idx = by_type["triangle"]
    assert tri_cb.data.shape == (2, 3)
    assert list(tri_idx) == [0, 3]

    quad_cb, quad_idx = by_type["quad"]
    assert quad_cb.data.shape == (1, 4)
    assert list(quad_idx) == [2]

    # The pentagon keeps all five nodes instead of being truncated to a quad.
    poly_cb, poly_idx = by_type["polygon"]
    assert poly_cb.data.shape == (1, 5)
    assert list(poly_idx) == [1]
    assert list(poly_cb.data[0]) == [3, 4, 5, 6, 7]


def test_split_cell_data_gathers_by_original_face_index():
    data = np.array([10.0, 11.0, 12.0, 13.0])  # per-face field values
    cells, cell_indices = _build_meshio_cells(_CONNECTIVITY)
    split = _split_cell_data(data, cell_indices)
    by_type = {cb.type: arr for cb, arr in zip(cells, split)}

    # Values follow their faces, not a contiguous block slice.
    assert list(by_type["triangle"]) == [10.0, 13.0]  # faces 0, 3
    assert list(by_type["polygon"]) == [11.0]  # face 1
    assert list(by_type["quad"]) == [12.0]  # face 2
