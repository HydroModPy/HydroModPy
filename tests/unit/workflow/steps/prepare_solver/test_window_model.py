"""A window of a chain is cut from the ``Model`` of the whole simulation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.time.window import ChainWindow
from hydromodpy.model.forcing.native import NativeSeries
from hydromodpy.model.initial.state import (
    CyclicStart,
    HeadRule,
    PriorState,
    SteadyStart,
)
from hydromodpy.model.model import ModelTime
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.workflow.steps.prepare_solver.model import (
    cut_native,
    cut_periods,
    window_model,
)
from tests._helpers.model_factory import make_model, time_grid

MONTHS = [pd.Timestamp(2020, month, 1) for month in range(1, 13)] + [pd.Timestamp(2021, 1, 1)]


def _window(index: int, count: int = 2, *, first: int = 0, stop: int = 6) -> ChainWindow:
    return ChainWindow(
        index=index,
        count=count,
        first_period=first,
        stop_period=stop,
        start=MONTHS[first],
        end=MONTHS[stop],
    )


def _whole(**members):
    return make_model(
        time=ModelTime(grid=time_grid(*[30.0] * 12), regime="transient", first_period_steady=True),
        **members,
    )


# --- one value per period is cut, anything else holds for every period ---


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (list(range(12)), [6, 7, 8, 9, 10, 11]),
        (tuple(range(12)), (6, 7, 8, 9, 10, 11)),
        (list(range(5)), list(range(5))),
        (2.5e-9, 2.5e-9),
        ("mean", "mean"),
        (
            {period: float(period) for period in range(12)},
            {0: 6.0, 1: 7.0, 2: 8.0, 3: 9.0, 4: 10.0, 5: 11.0},
        ),
        ({"a": 1.0}, {"a": 1.0}),
        (None, None),
    ],
    ids=["list", "tuple", "other length", "scalar", "text", "period table", "other keys", "none"],
)
def test_only_a_value_per_period_is_cut(values, expected) -> None:
    assert cut_periods(values, 6, 12, 12) == expected


def test_an_array_and_a_series_are_cut_by_position() -> None:
    array = cut_periods(np.arange(12.0), 6, 12, 12)
    series = cut_periods(pd.Series(np.arange(12.0)), 6, 12, 12)
    dated = cut_periods(pd.Series(np.arange(12.0), index=pd.DatetimeIndex(MONTHS[:12])), 6, 12, 12)

    assert array.tolist() == [6.0, 7.0, 8.0, 9.0, 10.0, 11.0]
    assert series.tolist() == array.tolist()
    assert list(series.index) == [0, 1, 2, 3, 4, 5], "a builder reads its periods from 0"
    assert dated.index[0] == MONTHS[6], "a dated series keeps its dates"


@pytest.mark.parametrize(
    ("shape", "cut_shape"),
    [((12, 4), (6, 4)), ((12, 2, 4), (6, 2, 4)), ((4, 12), (4, 12))],
    ids=["a map per period", "a map per layer and period", "periods on the second axis"],
)
def test_an_array_is_cut_on_its_first_axis_only(shape, cut_shape) -> None:
    values = np.arange(np.prod(shape), dtype=float).reshape(shape)

    cut = cut_periods(values, 6, 12, 12)

    assert cut.shape == cut_shape
    if cut_shape != shape:
        np.testing.assert_array_equal(cut, values[6:12])


# --- the model of a window ---


def test_the_forcings_of_a_window_are_cut_to_its_periods() -> None:
    whole = _whole(
        recharge=FlowRechargeConfig(values=[float(i) for i in range(12)], units="m/s"),
        lakes={
            "L": {
                "stage": 3.0,
                "runoff_rate": {"kind": "values", "values": [float(i) for i in range(12)]},
                "outlet": {"kind": "constant", "value": 1.0},
            }
        },
        sfr={"S": {"runoff": {"kind": "values", "values": [1.0, 2.0, 3.0]}}},
        initial=HeadRule("top"),
    )
    grid = time_grid(*[30.0] * 6)

    window = window_model(whole, _window(2, first=6, stop=12), grid=grid)

    assert window.recharge.values == [6.0, 7.0, 8.0, 9.0, 10.0, 11.0]
    assert window.lakes["L"]["runoff_rate"]["values"] == [6.0, 7.0, 8.0, 9.0, 10.0, 11.0]
    assert window.lakes["L"]["stage"] == 3.0
    assert window.lakes["L"]["outlet"] == {"kind": "constant", "value": 1.0}
    assert window.sfr["S"]["runoff"]["values"] == [1.0, 2.0, 3.0], "a length that is not nper stays"
    assert window.time.grid is grid
    assert whole.recharge.values == [float(i) for i in range(12)], "the whole model is untouched"
    assert whole.lakes["L"]["runoff_rate"]["values"] == [float(i) for i in range(12)]


def test_what_holds_for_every_period_is_shared_with_the_whole_model() -> None:
    whole = _whole(recharge=FlowRechargeConfig(values=2.0e-9, units="m/s"))
    window = window_model(whole, _window(2, first=6, stop=12), grid=time_grid(*[30.0] * 6))
    assert window.recharge is whole.recharge


@pytest.mark.parametrize(
    ("initial", "index", "count", "keeps_whole"),
    [
        (SteadyStart(), 1, 2, True),
        (CyclicStart(), 1, 3, True),
        (SteadyStart(), 1, 1, False),
        (HeadRule("top"), 1, 2, False),
        (PriorState(head=np.zeros((1, 6)), lake_stages={}, path="p"), 1, 2, False),
    ],
    ids=["steady", "cyclic", "one window", "top", "prior state"],
)
def test_the_first_window_of_a_chain_keeps_the_whole_model_in_its_computed_start(
    initial, index: int, count: int, keeps_whole: bool
) -> None:
    whole = _whole(initial=initial)

    window = window_model(
        whole, _window(index, count, first=0, stop=6), grid=time_grid(*[30.0] * 6)
    )

    over = getattr(window.initial, "over", None)
    assert (over is whole) is keeps_whole
    if keeps_whole:
        assert len(over.time.grid.period_lengths_seconds) == 12
        assert whole.initial is initial, "the whole model starts without a whole model of its own"


# --- the native recharge, dated ---


def _native() -> NativeSeries:
    return NativeSeries(starts=pd.DatetimeIndex(MONTHS), values=np.arange(12.0))


def test_the_native_recharge_is_cut_at_the_edges_of_the_window() -> None:
    cut = cut_native(_native(), _window(2, first=6, stop=12))
    assert list(cut.starts) == MONTHS[6:13]
    assert cut.values.tolist() == [6.0, 7.0, 8.0, 9.0, 10.0, 11.0]


def test_a_native_recharge_whose_steps_miss_the_window_edges_is_left_whole() -> None:
    offset = NativeSeries(
        starts=pd.DatetimeIndex(MONTHS) + pd.Timedelta(3, unit="D"), values=np.arange(12.0)
    )
    assert cut_native(offset, _window(2, first=6, stop=12)) is offset
    assert cut_native(None, _window(2, first=6, stop=12)) is None
