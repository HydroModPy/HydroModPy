"""Unit tests for shared simulation time-window helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.simulation.time import (
    apply_explicit_time_window_to_tgrids,
    resolve_simulation_time_grid,
    resolve_simulation_time_window,
    validate_recharge_coverage,
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
                SimpleNamespace(type="flow", solvers=["modflownwt"]),
            ],
        ),
        modflownwt=SimpleNamespace(
            tgrid=SimpleNamespace(start_datetime=None, end_datetime=None),
        ),
        modflow6=SimpleNamespace(
            tgrid=SimpleNamespace(start_datetime=None, end_datetime=None),
        ),
    )


def test_apply_simulation_time_window_updates_solver_tgrids() -> None:
    cfg = _make_cfg_with_time()

    apply_explicit_time_window_to_tgrids(cfg)

    assert str(cfg.modflownwt.tgrid.start_datetime).startswith("2020-01-01")
    assert str(cfg.modflownwt.tgrid.end_datetime).startswith("2020-01-03")
    assert cfg.modflownwt.tgrid.nper == 3
    assert cfg.modflownwt.tgrid.lenper == [1.0, 1.0, 1.0]
    assert cfg.modflownwt.tgrid.itmuni == "d"
    assert cfg.modflownwt.tgrid.ntsp == 1
    assert cfg.modflownwt.tgrid.tsmult == 1.0
    assert str(cfg.modflow6.tgrid.start_datetime).startswith("2020-01-01")
    assert str(cfg.modflow6.tgrid.end_datetime).startswith("2020-01-03")
    assert cfg.modflow6.tgrid.nper == 3
    assert cfg.modflow6.tgrid.lenper == [1.0, 1.0, 1.0]
    assert cfg.modflow6.tgrid.itmuni == "d"
    assert cfg.modflow6.tgrid.ntsp == 1
    assert cfg.modflow6.tgrid.tsmult == 1.0


def test_get_simulation_time_window_rejects_from_modflow_mode() -> None:
    cfg = _make_cfg_with_time(mode="from_modflow")

    with pytest.raises(ValueError, match="must be 'explicit'"):
        resolve_simulation_time_window(cfg)


def test_validate_recharge_coverage_raises_when_range_not_covered() -> None:
    cfg = _make_cfg_with_time(coverage_policy="error")
    window = resolve_simulation_time_window(cfg)
    recharge = pd.Series(
        [0.1, 0.2],
        index=pd.to_datetime(["2020-01-02 00:00:00", "2020-01-03 00:00:00"]),
    )

    with pytest.raises(ValueError, match="does not fully cover"):
        validate_recharge_coverage(recharge, window)


def test_validate_recharge_coverage_warns_when_policy_warn() -> None:
    cfg = _make_cfg_with_time(coverage_policy="warn")
    window = resolve_simulation_time_window(cfg)
    recharge = pd.Series(
        [0.1, 0.2],
        index=pd.to_datetime(["2020-01-02 00:00:00", "2020-01-03 00:00:00"]),
    )

    with pytest.warns(UserWarning, match="Recharge coverage check failed"):
        validate_recharge_coverage(recharge, window)


def test_validate_recharge_coverage_passes_for_full_coverage() -> None:
    cfg = _make_cfg_with_time(coverage_policy="error")
    window = resolve_simulation_time_window(cfg)
    recharge = pd.Series(
        [0.1, 0.2, 0.3],
        index=pd.to_datetime(
            ["2020-01-01 00:00:00", "2020-01-02 00:00:00", "2020-01-03 00:00:00"]
        ),
    )

    validate_recharge_coverage(recharge, window)


def test_validate_recharge_coverage_accepts_period_aligned_series() -> None:
    cfg = _make_cfg_with_time(step_value=10, step_unit="day", coverage_policy="error")
    cfg.simulation.time.start_datetime = "2020-01-01 00:00:00"
    cfg.simulation.time.end_datetime = "2020-01-30 00:00:00"
    window = resolve_simulation_time_window(cfg)
    recharge = pd.Series(
        [0.1, 0.2, 0.3],
        index=pd.to_datetime(
            ["2020-01-01 00:00:00", "2020-01-11 00:00:00", "2020-01-21 00:00:00"]
        ),
    )

    validate_recharge_coverage(recharge, window)


def test_apply_simulation_time_window_monthly_calendar_lengths() -> None:
    cfg = _make_cfg_with_time(step_value=1, step_unit="month")
    cfg.simulation.time.start_datetime = "2020-01-01 00:00:00"
    cfg.simulation.time.end_datetime = "2020-03-31 00:00:00"

    apply_explicit_time_window_to_tgrids(cfg)

    assert cfg.modflownwt.tgrid.nper == 3
    assert cfg.modflownwt.tgrid.lenper == [31.0, 29.0, 31.0]


def test_resolve_simulation_time_grid_explicit_mode() -> None:
    cfg = _make_cfg_with_time(step_value=10, step_unit="day")
    cfg.simulation.time.start_datetime = "2020-01-01 00:00:00"
    cfg.simulation.time.end_datetime = "2020-01-30 00:00:00"

    grid = resolve_simulation_time_grid(cfg)

    assert grid is not None
    assert grid.nper == 3
    assert list(grid.period_lengths_days) == [10.0, 10.0, 10.0]
    assert list(grid.period_starts) == [
        pd.Timestamp("2020-01-01 00:00:00"),
        pd.Timestamp("2020-01-11 00:00:00"),
        pd.Timestamp("2020-01-21 00:00:00"),
    ]


def test_resolve_simulation_time_grid_rejects_from_modflow_mode() -> None:
    cfg = _make_cfg_with_time(mode="from_modflow")

    with pytest.raises(ValueError, match="must be 'explicit'"):
        _ = resolve_simulation_time_grid(cfg)


def test_apply_simulation_time_window_raises_when_end_not_aligned_with_step() -> None:
    cfg = _make_cfg_with_time(step_value=2, step_unit="day")
    cfg.simulation.time.start_datetime = "2020-01-01 00:00:00"
    cfg.simulation.time.end_datetime = "2020-01-03 00:00:00"

    with pytest.raises(ValueError, match="not aligned with step_value/step_unit"):
        apply_explicit_time_window_to_tgrids(cfg)
