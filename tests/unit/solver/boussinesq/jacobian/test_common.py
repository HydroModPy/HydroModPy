"""Helpers shared by the Boussinesq Jacobian builders: a scalar or vector payload per cell."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.boussinesq.jacobian.common import as_cell_vector

pytestmark = pytest.mark.fast

N_CELLS = 3

CELL_VECTORS = [
    pytest.param(None, [0.0, 0.0, 0.0], id="none is zero"),
    pytest.param([], [0.0, 0.0, 0.0], id="empty is zero"),
    pytest.param(2.5, [2.5, 2.5, 2.5], id="scalar fills"),
    pytest.param([4.0], [4.0, 4.0, 4.0], id="one value fills"),
    pytest.param([1.0, 2.0, 3.0], [1.0, 2.0, 3.0], id="one value per cell"),
]


@pytest.mark.parametrize(("values", "expected"), CELL_VECTORS)
def test_as_cell_vector(values, expected) -> None:
    np.testing.assert_array_equal(as_cell_vector(values, n_cells=N_CELLS), expected)


def test_refuses_a_vector_of_the_wrong_length() -> None:
    with pytest.raises(ValueError, match="Expected scalar or vector of length 3; got 2"):
        as_cell_vector([1.0, 2.0], n_cells=N_CELLS)
