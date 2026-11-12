"""Unit tests for shared simulation time-window helpers."""

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


def _make_cfg_with_time(
    *,
    coverage_policy: str = "error",
    mode: str = "explicit",
    step_value: int = 1,
    step_unit: str = "day",
) -> SimpleNamespace:
    return SimpleNamespace(
        simulation=SimpleNamespace(
            time=SimpleNamespace(
                mode=mode,
                start_datetime="2020-01-01 00:00:00",
                end_datetime="2020-01-03 00:00:00",
                step_value=step_value,
                step_unit=step_unit,
                coverage_policy=coverage_policy,
            ),
            process=[
                SimpleNamespace(kind="flow", solvers=["modflow_nwt"]),
            ],
        ),
        flow=SimpleNamespace(flow_regime="transient"),
    )


def test_resolve_simulation_time_grid_explicit_mode() -> None:
    cfg = _make_cfg_with_time(step_value=10, step_unit="day")
    cfg.simulation.time.start_datetime = "2020-01-01 00:00:00"
    cfg.simulation.time.end_datetime = "2020-01-30 00:00:00"

    grid = resolve_simulation_time_grid(cfg)

    assert grid is not None
    assert grid.nper == 3
    assert list(grid.period_lengths_seconds) == [864000.0, 864000.0, 864000.0]
    assert list(grid.period_starts) == [
        pd.Timestamp("2020-01-01 00:00:00"),
        pd.Timestamp("2020-01-11 00:00:00"),
        pd.Timestamp("2020-01-21 00:00:00"),
    ]


def test_resolve_simulation_time_grid_rejects_from_modflow_mode() -> None:
    cfg = _make_cfg_with_time(mode="from_modflow")

    with pytest.raises(ValueError, match="must be 'explicit'"):
        _ = resolve_simulation_time_grid(cfg)


def test_require_flow_simulation_time_grid_requires_window_for_flow_process() -> None:
    cfg = _make_cfg_with_time()
    cfg.simulation.time = None
    cfg.flow = SimpleNamespace(flow_regime="transient")

    with pytest.raises(
        ValueError, match=r"Launcher flow processes require a valid \[simulation\.time\] section"
    ):
        require_flow_simulation_time_grid(cfg)


def test_require_flow_simulation_time_grid_keeps_window_optional_without_flow_process() -> None:
    cfg = _make_cfg_with_time()
    cfg.simulation.time = None
    cfg.simulation.process = [SimpleNamespace(kind="transport", solvers=["mt3dms"])]

    assert require_flow_simulation_time_grid(cfg) is None


def test_resolve_simulation_time_grid_raises_when_end_not_aligned_with_step() -> None:
    cfg = _make_cfg_with_time(step_value=2, step_unit="day")
    cfg.simulation.time.start_datetime = "2020-01-01 00:00:00"
    cfg.simulation.time.end_datetime = "2020-01-03 00:00:00"

    with pytest.raises(ValueError, match="not aligned with step_value/step_unit"):
        resolve_simulation_time_grid(cfg)


def test_simulation_time_pandas_frequency_hourly_uses_lowercase_alias() -> None:
    cfg = _make_cfg_with_time(step_value=6, step_unit="hour")
    window = resolve_simulation_time_window(cfg)

    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        freq = simulation_time_pandas_frequency(window)

    assert freq == "6h"
    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        pd.date_range(cfg.simulation.time.start_datetime, periods=3, freq=freq)


def test_simulation_time_window_rejects_bare_step_value_without_unit() -> None:
    cfg = _make_cfg_with_time()
    cfg.simulation.time.step_value = 1
    cfg.simulation.time.step_unit = None

    with pytest.raises(ValueError, match="simulation.time.step_value has no unit"):
        resolve_simulation_time_window(cfg)


def test_simulation_time_window_reports_sign_before_missing_unit() -> None:
    """A negative step_value with no unit gets the sign diagnosis, not 'has no unit'."""
    cfg = _make_cfg_with_time()
    cfg.simulation.time.step_value = -5
    cfg.simulation.time.step_unit = None

    with pytest.raises(ValueError, match="must be a positive integer"):
        resolve_simulation_time_window(cfg)


def test_simulation_time_window_reports_type_before_missing_unit() -> None:
    """A boolean step_value with no unit gets the type diagnosis, not 'has no unit'."""
    cfg = _make_cfg_with_time()
    cfg.simulation.time.step_value = True
    cfg.simulation.time.step_unit = None

    with pytest.raises(ValueError, match="must be a positive integer"):
        resolve_simulation_time_window(cfg)


def test_resolve_simulation_time_grid_accepts_inline_step_value_unit() -> None:
    cfg = _make_cfg_with_time(step_value=1, step_unit="day")
    cfg.simulation.time.step_value = "30 day"
    cfg.simulation.time.step_unit = None
    cfg.simulation.time.start_datetime = "2020-01-01 00:00:00"
    cfg.simulation.time.end_datetime = "2020-03-30 00:00:00"

    grid = resolve_simulation_time_grid(cfg)

    assert grid is not None
    assert grid.nper == 3
    assert grid.period_lengths_seconds == (2592000.0, 2592000.0, 2592000.0)


def _steady_cfg(
    *,
    start: str = "2020-01-01",
    end: str = "2021-12-31",
    step_value: object = "1 month",
    step_unit: str | None = None,
) -> SimpleNamespace:
    cfg = _make_cfg_with_time()
    cfg.simulation.time.start_datetime = start
    cfg.simulation.time.end_datetime = end
    cfg.simulation.time.step_value = step_value
    cfg.simulation.time.step_unit = step_unit
    cfg.flow = SimpleNamespace(flow_regime="steady")
    return cfg


def test_a_steady_window_need_not_align_with_the_step() -> None:
    grid = resolve_simulation_time_grid(_steady_cfg(end="2021-12-15"))

    assert grid is not None
    assert grid.nper == 1
    assert grid.boundaries[-1] == pd.Timestamp("2021-12-16")
