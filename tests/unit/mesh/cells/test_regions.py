"""``family_regions`` labels the cells that stay joined once the faces of a family are cut.

The labels number the regions in the order of their first cell. A mesh whose
cut family has no face is one region.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.mesh.cells.regions import family_regions
from tests._helpers.mesh_cases import regular_mesh


def test_no_face_is_one_region() -> None:
    grid = regular_mesh(3, 4, dx=10.0)

    labels = family_regions(grid, "lakes")

    assert labels.dtype == np.int64
    assert labels.tolist() == [0] * grid.n_cells
