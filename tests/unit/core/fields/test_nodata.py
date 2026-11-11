"""The nodata sentinels of a raster and of a MODFLOW head, and the cells that hold a value.

A raster carries ``RASTER_NODATA``. A MODFLOW head carries a finite sentinel of
about 1e30 that an ``isfinite`` test lets through, so a magnitude above
``SENTINEL_ABS_THRESHOLD`` is a sentinel, never a result.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.fields.nodata import (
    RASTER_NODATA,
    SENTINEL_ABS_THRESHOLD,
    valid_cells,
)

# One row per case: values, the nodata of the raster, and the cells that hold a value.
_VALID_CELLS = [
    pytest.param([1.0, -9999.0, 3.0], -9999.0, [True, False, True], id="raster_nodata"),
    pytest.param([1.0, -9999.0, 3.0], None, [True, True, True], id="no_nodata_kept"),
    pytest.param([1.0, np.nan, 3.0], None, [True, False, True], id="nan_is_never_a_value"),
    pytest.param([1.0, np.nan, 3.0], np.nan, [True, False, True], id="nan_nodata_finite_test_only"),
    pytest.param([np.inf, -np.inf, 0.0], -9999.0, [False, False, True], id="infinite_is_no_value"),
    pytest.param([0.0, -0.0, 1e-30], -9999.0, [True, True, True], id="zero_is_a_value"),
    pytest.param([-32768.0, -9999.0], -32768.0, [False, True], id="own_nodata_of_the_raster"),
    pytest.param([1e30, -6e30], -9999.0, [True, True], id="finite_sentinel_slips_through"),
]


@pytest.mark.parametrize(("values", "nodata", "expected"), _VALID_CELLS)
def test_valid_cells_are_the_finite_cells_that_differ_from_the_nodata(values, nodata, expected):
    mask = valid_cells(np.array(values), nodata)
    assert mask.tolist() == expected


def test_the_default_raster_nodata_is_the_one_every_writer_uses() -> None:
    assert RASTER_NODATA == -9999.0
    assert not valid_cells(np.array([RASTER_NODATA]), RASTER_NODATA)[0]


# One row per value: the magnitude, and whether the head sentinel threshold calls it a sentinel.
_SENTINEL_THRESHOLD = [
    pytest.param(1e30, True, id="hdry"),
    pytest.param(-1e30, True, id="hnoflo_negative"),
    pytest.param(-6e30, True, id="other_package"),
    pytest.param(3e30, True, id="mf6_dnodata"),
    pytest.param(1e19, False, id="below_the_threshold"),
    pytest.param(-9999.0, False, id="raster_nodata_is_not_a_head_sentinel"),
    pytest.param(250.0, False, id="a_head"),
]


@pytest.mark.parametrize(("value", "is_sentinel"), _SENTINEL_THRESHOLD)
def test_a_magnitude_above_the_threshold_is_a_sentinel(value, is_sentinel) -> None:
    assert (abs(value) > SENTINEL_ABS_THRESHOLD) is is_sentinel
