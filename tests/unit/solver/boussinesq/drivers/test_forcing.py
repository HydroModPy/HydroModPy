"""Drainage conductance of a run, in m2/s, with the cells of an ocean boundary muted."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.boussinesq.drivers.forcing import apply_ocean_drainage_mask

OCEAN_CELLS = np.asarray([False, True, False, True])

DRAINAGE = [
    pytest.param(1.0e-5, OCEAN_CELLS, [1.0e-5, 0.0, 1.0e-5, 0.0], id="ocean cells are muted"),
    pytest.param(1.0e-5, np.zeros(4, dtype=bool), 1.0e-5, id="no ocean cell"),
    pytest.param(0.0, OCEAN_CELLS, 0.0, id="no drainage"),
]


@pytest.mark.parametrize(("value_m2_s", "ocean", "expected"), DRAINAGE)
def test_ocean_drainage_mask(value_m2_s: float, ocean: np.ndarray, expected) -> None:
    conductance = apply_ocean_drainage_mask(
        n_cells=4, drainage_value_m2_s=value_m2_s, ocean_supported_cell_mask=ocean
    )

    np.testing.assert_array_equal(conductance, expected)
