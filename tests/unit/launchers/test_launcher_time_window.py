"""The simulation time window and its stress-period grid, from ``[simulation.time]``.

Dates are calendar timestamps, steps are a count of a unit (day, hour, month) and
period lengths are in seconds."""

from __future__ import annotations

import warnings
from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.core.time.window import (
    require_flow_simulation_time_grid,
    resolve_simulation_time_grid,
    resolve_simulation_time_window,
    simulation_time_pandas_frequency,
)


def a_config(regime: str = "transient", **time) -> SimpleNamespace:
    """A flow config over 2020-01-01 to 2020-01-03 in 1 day steps, with ``time`` overriding."""
    fields = {
        "mode": "explicit",
        "start_datetime": "2020-01-01 00:00:00",
        "end_datetime": "2020-01-03 00:00:00",
        "step_value": 1,
        "step_unit": "day",
        "coverage_policy": "error",
    } | time
    return SimpleNamespace(
        simulation=SimpleNamespace(
            time=SimpleNamespace(**fields),
            process=[SimpleNamespace(kind="flow", solvers=["modflow_nwt"])],
        ),
        flow=SimpleNamespace(flow_regime=regime),
    )


def test_explicit_grid() -> None:
    cfg = a_config(end_datetime="2020-01-30 00:00:00", step_value=10)

    grid = resolve_simulation_time_grid(cfg)

    assert grid.nper == 3
    assert list(grid.period_lengths_seconds) == [864000.0, 864000.0, 864000.0]
    assert list(grid.period_starts) == [
        pd.Timestamp("2020-01-01 00:00:00"),
        pd.Timestamp("2020-01-11 00:00:00"),
        pd.Timestamp("2020-01-21 00:00:00"),
    ]


def test_inline_step_value_and_unit() -> None:
    cfg = a_config(end_datetime="2020-03-30 00:00:00", step_value="30 day", step_unit=None)

    grid = resolve_simulation_time_grid(cfg)

    assert grid.nper == 3
    assert grid.period_lengths_seconds == (2592000.0, 2592000.0, 2592000.0)


def test_steady_window_need_not_align_with_the_step() -> None:
    cfg = a_config(
        "steady",
        start_datetime="2020-01-01",
        end_datetime="2021-12-15",
        step_value="1 month",
        step_unit=None,
    )

    grid = resolve_simulation_time_grid(cfg)

    assert grid.nper == 1
    assert grid.boundaries[-1] == pd.Timestamp("2021-12-16")


def test_hourly_frequency_uses_lowercase_alias() -> None:
    cfg = a_config(step_value=6, step_unit="hour")
    window = resolve_simulation_time_window(cfg)

    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        freq = simulation_time_pandas_frequency(window)
        pd.date_range(cfg.simulation.time.start_datetime, periods=3, freq=freq)

    assert freq == "6h"


def test_flow_process_needs_no_window_without_flow() -> None:
    cfg = a_config()
    cfg.simulation.time = None
    cfg.simulation.process = [SimpleNamespace(kind="transport", solvers=["mt3dms"])]

    assert require_flow_simulation_time_grid(cfg) is None


# (changes to [simulation.time], part of the message that names the fix)
REFUSED_TIMES = [
    pytest.param({"mode": "from_modflow"}, "must be 'explicit'", id="from_modflow mode"),
    pytest.param(
        {"step_value": 2},
        "not aligned with step_value/step_unit",
        id="end not aligned with the step",
    ),
    pytest.param(
        {"step_unit": None},
        "simulation.time.step_value has no unit",
        id="step value without unit",
    ),
    # The sign and the type are diagnosed before the missing unit.
    pytest.param(
        {"step_value": -5, "step_unit": None},
        "must be a positive integer",
        id="negative step value",
    ),
    pytest.param(
        {"step_value": True, "step_unit": None},
        "must be a positive integer",
        id="boolean step value",
    ),
]


@pytest.mark.parametrize(("time", "message"), REFUSED_TIMES)
def test_refused_times(time, message) -> None:
    with pytest.raises(ValueError, match=message):
        resolve_simulation_time_grid(a_config(**time))


def test_flow_process_requires_a_window() -> None:
    cfg = a_config()
    cfg.simulation.time = None

    with pytest.raises(
        ValueError, match=r"Launcher flow processes require a valid \[simulation\.time\] section"
    ):
        require_flow_simulation_time_grid(cfg)
