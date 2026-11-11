"""One budget record of a stamp is the mean of its steps, with inflow and outflow kept apart.

A MODFLOW 6 cell budget is positive where water enters the aquifer and negative where it leaves. A
cell that changes sign inside one period counts its inflow and its outflow, as the volumes of the
period do, so the two means never cancel. The in and out totals are in m3/s.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.modflow6.extractors.budget import _period_mean_record

_SPT = 86400.0


class _Cbb:
    """A cell budget reader that serves one array per step."""

    def __init__(self, arrays: list[np.ndarray]) -> None:
        self._arrays = arrays

    def read_record(self, index: int) -> np.ndarray:
        return self._arrays[index]


def _record(arrays, weights=None, *, catchment=None, with_field=True):
    weights = [1.0 / len(arrays)] * len(arrays) if weights is None else weights
    return _period_mean_record(
        _Cbb([np.asarray(a, dtype=float).reshape(1, 1, -1) for a in arrays]),
        list(enumerate(weights)),
        component="recharge",
        t=0,
        nlay=1,
        n_cells=np.asarray(arrays[0]).size,
        seconds_per_time_unit=_SPT,
        catchment_cells=catchment,
        with_field=with_field,
    )


# One row per step set: the cell values of each step in m3/day, the step weights, and the mean
# inflow and outflow of the period in m3/day. The outflow is signed here and taken as a magnitude
# when it is written.
_PERIODS = [
    pytest.param([[1.0, -2.0, 3.0, 0.0]], None, 4.0, -2.0, id="one_step_split_by_sign"),
    pytest.param([[2.0]], None, 2.0, 0.0, id="only_inflow"),
    pytest.param([[-5.0]], None, 0.0, -5.0, id="only_outflow"),
    pytest.param([[1.0], [-1.0]], [0.5, 0.5], 0.5, -0.5, id="a_cell_changing_sign_counts_both"),
    pytest.param([[4.0], [0.0]], [0.75, 0.25], 3.0, 0.0, id="weights_by_step_length"),
    pytest.param([[0.0, -0.0]], None, 0.0, 0.0, id="negative_zero_is_nothing"),
]


@pytest.mark.parametrize(("steps", "weights", "inflow", "outflow"), _PERIODS)
def test_a_period_keeps_the_inflow_and_the_outflow_apart(steps, weights, inflow, outflow) -> None:
    record = _record(steps, weights)

    assert record.flux_in == pytest.approx(inflow / _SPT, abs=1e-18)
    assert record.flux_out == pytest.approx(outflow / _SPT, abs=1e-18)
    assert abs(record.flux_out) >= 0.0


def test_the_cell_field_stays_in_the_unit_of_the_file() -> None:
    record = _record([[1.0, -2.0]], with_field=True)

    np.testing.assert_allclose(record.field.reshape(-1), [1.0, -2.0])
    assert _record([[1.0, -2.0]], with_field=False).field is None


def test_the_catchment_totals_split_by_sign_over_its_cells_only() -> None:
    cells = np.array([0, 1])

    record = _record([[1.0, -2.0, 7.0, -9.0]], catchment=cells)

    assert record.basin_in == pytest.approx(1.0 / _SPT)
    assert record.basin_out == pytest.approx(-2.0 / _SPT)
    assert record.flux_in == pytest.approx(8.0 / _SPT)
    assert record.flux_out == pytest.approx(-11.0 / _SPT)


def test_a_period_whose_steps_cannot_be_read_gives_nothing() -> None:
    class _Broken:
        def read_record(self, _index: int):
            raise OSError("truncated")

    record = _period_mean_record(
        _Broken(),
        [(0, 1.0)],
        component="recharge",
        t=0,
        nlay=1,
        n_cells=1,
        seconds_per_time_unit=_SPT,
        catchment_cells=None,
    )

    assert record is None
