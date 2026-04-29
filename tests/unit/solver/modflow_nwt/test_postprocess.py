from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.modflow_nwt.nwt.postprocess import (
    compute_outlet_discharge_east_side_m3_s,
)


def test_compute_outlet_discharge_east_side_m3_s_sums_east_boundary_outflow() -> None:
    dtype = np.dtype([("node", "<i4"), ("q", "<f4")])
    record = np.array(
        [
            (1, 2.0e-4),
            (4, -3.0e-4),
            (5, 1.0e-4),
            (8, -4.5e-4),
        ],
        dtype=dtype,
    )

    discharge_m3_s = compute_outlet_discharge_east_side_m3_s(
        [record],
        nrow=2,
        ncol=4,
    )

    assert discharge_m3_s == pytest.approx(7.5e-4)


def test_compute_outlet_discharge_east_side_m3_s_returns_zero_without_records() -> None:
    assert compute_outlet_discharge_east_side_m3_s(None, nrow=2, ncol=4) == 0.0
