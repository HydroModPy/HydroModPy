"""Unit tests for launcher-level simulation time-window helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from launchers.process_simulation.launcher import HydroModPyLauncher


def _make_launcher_with_time(*, coverage_policy: str = "error") -> HydroModPyLauncher:
    launcher = HydroModPyLauncher.__new__(HydroModPyLauncher)
    launcher.cfg = SimpleNamespace(
        simulation=SimpleNamespace(
            time=SimpleNamespace(
                start_datetime="2020-01-01 00:00:00",
                end_datetime="2020-01-03 00:00:00",
                coverage_policy=coverage_policy,
            )
        ),
        modflownwt=SimpleNamespace(
            tgrid=SimpleNamespace(start_datetime=None, end_datetime=None),
        ),
        modflow6=SimpleNamespace(
            tgrid=SimpleNamespace(start_datetime=None, end_datetime=None),
        ),
    )
    return launcher


def test_apply_simulation_time_window_updates_solver_tgrids() -> None:
    launcher = _make_launcher_with_time()

    launcher._apply_simulation_time_window_to_tgrids()

    assert str(launcher.cfg.modflownwt.tgrid.start_datetime).startswith("2020-01-01")
    assert str(launcher.cfg.modflownwt.tgrid.end_datetime).startswith("2020-01-03")
    assert str(launcher.cfg.modflow6.tgrid.start_datetime).startswith("2020-01-01")
    assert str(launcher.cfg.modflow6.tgrid.end_datetime).startswith("2020-01-03")


def test_validate_recharge_coverage_raises_when_range_not_covered() -> None:
    launcher = _make_launcher_with_time(coverage_policy="error")
    recharge = pd.Series(
        [0.1, 0.2],
        index=pd.to_datetime(["2020-01-02 00:00:00", "2020-01-03 00:00:00"]),
    )

    with pytest.raises(ValueError, match="does not fully cover"):
        launcher._validate_recharge_coverage(recharge)


def test_validate_recharge_coverage_warns_when_policy_warn() -> None:
    launcher = _make_launcher_with_time(coverage_policy="warn")
    recharge = pd.Series(
        [0.1, 0.2],
        index=pd.to_datetime(["2020-01-02 00:00:00", "2020-01-03 00:00:00"]),
    )

    with pytest.warns(UserWarning, match="Recharge coverage check failed"):
        launcher._validate_recharge_coverage(recharge)


def test_validate_recharge_coverage_passes_for_full_coverage() -> None:
    launcher = _make_launcher_with_time(coverage_policy="error")
    recharge = pd.Series(
        [0.1, 0.2, 0.3],
        index=pd.to_datetime(
            ["2020-01-01 00:00:00", "2020-01-02 00:00:00", "2020-01-03 00:00:00"]
        ),
    )

    launcher._validate_recharge_coverage(recharge)
