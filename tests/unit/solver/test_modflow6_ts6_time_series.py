"""Unit tests for the package-agnostic MF6 TS6 helper and the LAK TS6 seam.

Three things are checked without running a solver:

* ``build_ts6_table`` packs same-axis series into FloPy records and rejects
  collisions, mismatched axes, and non-increasing times;
* ``attach_time_series`` is package-agnostic: it attaches a series to a WEL
  package (a second package type) through the shared ``.ts`` protocol, proving
  the helper is not LAK-specific;
* a long, non-constant LAK forcing in ``ts6`` mode produces a TS6 series and a
  ``perioddata`` row that references the series NAME (a string), not a float.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.exceptions import SolverInputError
from hydromodpy.core.time import ResolvedSimulationTimeWindow, build_simulation_time_boundaries
from hydromodpy.physics.flow.sinks_sources.wells import FlowWellForcingCsvConfig
from hydromodpy.solver.modflow6.builders.lake import build_lake_period_data, resolve_use_ts6
from hydromodpy.solver.modflow6.common.time_series import (
    Ts6Series,
    attach_time_series,
    build_ts6_table,
)


def test_build_ts6_table_packs_same_axis_series_into_columns() -> None:
    series = [
        Ts6Series(name="a", times=(0.0, 10.0, 20.0), values=(1.0, 2.0, 3.0)),
        Ts6Series(name="b", times=(0.0, 10.0, 20.0), values=(4.0, 5.0, 6.0)),
    ]
    timeseries, names, methods = build_ts6_table(series)
    assert names == ["a", "b"]
    assert methods == ["stepwise", "stepwise"]
    assert timeseries == [[0.0, 1.0, 4.0], [10.0, 2.0, 5.0], [20.0, 3.0, 6.0]]


def test_build_ts6_table_rejects_mismatched_axes_and_collisions() -> None:
    with pytest.raises(SolverInputError, match="same time axis"):
        build_ts6_table(
            [
                Ts6Series(name="a", times=(0.0, 10.0), values=(1.0, 2.0)),
                Ts6Series(name="b", times=(0.0, 20.0), values=(3.0, 4.0)),
            ]
        )
    with pytest.raises(SolverInputError, match="unique"):
        build_ts6_table(
            [
                Ts6Series(name="dup", times=(0.0, 10.0), values=(1.0, 2.0)),
                Ts6Series(name="dup", times=(0.0, 10.0), values=(3.0, 4.0)),
            ]
        )


def test_build_ts6_table_rejects_non_increasing_times() -> None:
    with pytest.raises(SolverInputError, match="strictly increasing"):
        build_ts6_table([Ts6Series(name="a", times=(0.0, 0.0), values=(1.0, 2.0))])


def test_attach_time_series_is_package_agnostic_on_a_wel(tmp_path: Path) -> None:
    # Proves generality: the helper attaches a series to a WEL (a different
    # package type than LAK) through the shared ``.ts`` child-package protocol.
    import flopy

    sim = flopy.mf6.MFSimulation(sim_name="welts", sim_ws=str(tmp_path))
    flopy.mf6.ModflowTdis(sim, time_units="seconds", nper=3, perioddata=[(10.0, 1, 1.0)] * 3)
    gwf = flopy.mf6.ModflowGwf(sim, modelname="welts")
    flopy.mf6.ModflowGwfdis(gwf, nlay=1, nrow=1, ncol=1, top=10.0, botm=0.0)
    flopy.mf6.ModflowGwfic(gwf, strt=5.0)
    flopy.mf6.ModflowGwfnpf(gwf, k=1.0)
    wel = flopy.mf6.ModflowGwfwel(gwf, stress_period_data={0: [[(0, 0, 0), "w_rate"]]})
    attach_time_series(
        wel,
        [Ts6Series(name="w_rate", times=(0.0, 10.0, 20.0), values=(-1.0, -2.0, -3.0))],
        filename="welts.wel.ts",
    )
    sim.write_simulation(silent=True)

    ts_file = tmp_path / "welts.wel.ts"
    assert ts_file.exists()
    text = ts_file.read_text().upper()
    assert "W_RATE" in text
    assert "STEPWISE" in text
    # The WEL file references the external series via a TS6 FILEIN record.
    wel_text = (tmp_path / "welts.wel").read_text().upper()
    assert "TS6" in wel_text and "FILEIN" in wel_text


def test_resolve_use_ts6_keeps_constant_inline_and_routes_long_series() -> None:
    constant = {"kind": "constant", "value": 1.0}
    csv = {"kind": "csv", "path_file": "x.csv"}
    # A constant forcing is never routed to TS6, regardless of mode / nper.
    assert resolve_use_ts6(constant, mode="ts6", nper=999, min_periods=10) is False
    # inline mode never routes a non-constant forcing.
    assert resolve_use_ts6(csv, mode="inline", nper=999, min_periods=10) is False
    # auto routes only above the threshold.
    assert resolve_use_ts6(csv, mode="auto", nper=5, min_periods=10) is False
    assert resolve_use_ts6(csv, mode="auto", nper=50, min_periods=10) is True
    # ts6 routes any non-constant forcing on a multi-period model.
    assert resolve_use_ts6(csv, mode="ts6", nper=5, min_periods=10) is True


@dataclass
class _FakeProcessSpecific:
    lak_forcing_mode: str
    ts6_min_periods: int


@dataclass
class _FakeConfig:
    process_specific: _FakeProcessSpecific


@dataclass
class _FakeTimeGrid:
    window: ResolvedSimulationTimeWindow


class _FakeModel:
    def __init__(self, *, window, nper, perlen, mode, min_periods) -> None:
        self.time_grid = _FakeTimeGrid(window=window)
        self.nper = nper
        self.perlen = perlen
        self.modflow_config = _FakeConfig(
            process_specific=_FakeProcessSpecific(
                lak_forcing_mode=mode, ts6_min_periods=min_periods
            )
        )


def _daily_window_and_csv(tmp_path: Path, n_days: int):
    start = pd.Timestamp("2003-01-01")
    window = ResolvedSimulationTimeWindow(
        start=start,
        end=start + pd.Timedelta(days=n_days),
        step_value=1,
        step_unit="day",
        coverage_policy="ignore",
    )
    boundaries = build_simulation_time_boundaries(window)
    nper = len(boundaries) - 1
    starts = boundaries[:-1]
    values = [float(86400.0 * (i + 1)) for i in range(nper)]
    csv = tmp_path / "inflow.csv"
    frame = pd.DataFrame({"date": [s.date().isoformat() for s in starts], "value": values})
    frame.to_csv(csv, index=False)
    perlen = np.full(nper, 86400.0)
    return window, csv, nper, perlen, values


def test_long_lak_forcing_emits_ts6_series_name_not_a_float(tmp_path: Path) -> None:
    # A long, non-constant LAK inflow in ts6 mode must surface a Ts6Series and a
    # perioddata row that references the series NAME (a string), not a float.
    window, csv, nper, perlen, values = _daily_window_and_csv(tmp_path, n_days=130)
    model = _FakeModel(window=window, nper=nper, perlen=perlen, mode="ts6", min_periods=120)
    forcing = FlowWellForcingCsvConfig(
        path_file=Path(csv), value_column="value", date_column="date", units="m3/s"
    )
    lakes = {"lac0": {"inflow": forcing}}
    rows, ts_specs = build_lake_period_data(model, lakes=lakes)

    assert len(ts_specs) == 1
    spec = ts_specs[0]
    assert spec.name == "lak0_inflow"
    assert spec.interpolation == "stepwise"
    # nper period-start breakpoints plus one terminal breakpoint at the sim end
    # so MF6 can integrate the STEPWISE series over the final period.
    assert len(spec.times) == nper + 1
    assert len(spec.values) == nper + 1
    assert spec.times[0] == 0.0
    # Period starts are cumulative seconds: second period starts after 86400 s.
    assert spec.times[1] == pytest.approx(86400.0)
    # Strictly increasing time axis (build_ts6_table also enforces this).
    assert all(b > a for a, b in zip(spec.times, spec.times[1:]))
    assert spec.values[0] == pytest.approx(values[0])
    # The terminal breakpoint repeats the last period value (STEPWISE-neutral).
    assert spec.values[-1] == pytest.approx(values[-1])
    # The matching perioddata row (in period 0) carries the series NAME (a
    # string), not a float; the TS6 file holds the per-period values.
    assert set(rows) == {0}
    assert rows[0] == [[0, "inflow", "lak0_inflow"]]
    assert isinstance(rows[0][0][2], str)


def test_auto_mode_below_threshold_expands_inline_per_period(tmp_path: Path) -> None:
    # Below the threshold, auto mode keeps the forcing inline: it must be expanded
    # per stress period (never dropped) and produce no TS6 series. This pins the
    # fix for the silent-drop bug where a sub-threshold non-constant forcing
    # vanished from the LAK PERIOD block.
    window, csv, nper, perlen, values = _daily_window_and_csv(tmp_path, n_days=5)
    model = _FakeModel(window=window, nper=nper, perlen=perlen, mode="auto", min_periods=120)
    forcing = FlowWellForcingCsvConfig(
        path_file=Path(csv), value_column="value", date_column="date", units="m3/s"
    )
    lakes = {"lac0": {"inflow": forcing}}
    rows, ts_specs = build_lake_period_data(model, lakes=lakes)
    assert ts_specs == []
    # Every period carries its own inflow value (the daily values are distinct).
    assert set(rows) == set(range(nper))
    for kper in range(nper):
        assert rows[kper] == [[0, "inflow", pytest.approx(values[kper])]]


def test_inline_mode_collapses_a_constant_tail_to_one_row(tmp_path: Path) -> None:
    # Inline expansion emits a row only when the value changes: a forcing that is
    # constant after the first period must collapse to a single period-0 row.
    window, csv, nper, perlen, _values = _daily_window_and_csv(tmp_path, n_days=4)
    # Overwrite the CSV with a flat chronicle so every period resolves to 7.0.
    starts = build_simulation_time_boundaries(window)[:-1]
    pd.DataFrame({"date": [s.date().isoformat() for s in starts], "value": [7.0] * nper}).to_csv(
        csv, index=False
    )
    model = _FakeModel(window=window, nper=nper, perlen=perlen, mode="inline", min_periods=120)
    forcing = FlowWellForcingCsvConfig(
        path_file=Path(csv), value_column="value", date_column="date", units="m3/s"
    )
    rows, ts_specs = build_lake_period_data(model, lakes={"lac0": {"inflow": forcing}})
    assert ts_specs == []
    assert set(rows) == {0}
    assert rows[0] == [[0, "inflow", pytest.approx(7.0)]]


def test_managed_lake_forcing_is_zeroed_on_steady_warmup(tmp_path: Path) -> None:
    # A steady spin-up has no lake storage term, so a managed transfer that does
    # not balance the natural budget has no equilibrium stage and the solve
    # diverges. Managed transfers (inflow/withdrawal) must be held at zero on the
    # steady period(s); the transient periods keep their real values.
    window, csv, nper, perlen, values = _daily_window_and_csv(tmp_path, n_days=5)
    model = _FakeModel(window=window, nper=nper, perlen=perlen, mode="inline", min_periods=120)
    model.steady = (True,) + (False,) * (nper - 1)
    forcing = FlowWellForcingCsvConfig(
        path_file=Path(csv), value_column="value", date_column="date", units="m3/s"
    )
    rows, _ = build_lake_period_data(model, lakes={"lac0": {"withdrawal": forcing}})
    # Steady period 0 is neutralized to 0; the transient periods keep real values.
    assert rows[0] == [[0, "withdrawal", pytest.approx(0.0)]]
    for kper in range(1, nper):
        assert rows[kper] == [[0, "withdrawal", pytest.approx(values[kper])]]


def test_natural_lake_forcing_is_kept_on_steady_warmup(tmp_path: Path) -> None:
    # Natural fluxes (runoff/rainfall/evaporation) are not management: they stay
    # on the steady spin-up so the lake equilibrates under real hydrology.
    window, csv, nper, perlen, values = _daily_window_and_csv(tmp_path, n_days=5)
    model = _FakeModel(window=window, nper=nper, perlen=perlen, mode="inline", min_periods=120)
    model.steady = (True,) + (False,) * (nper - 1)
    forcing = FlowWellForcingCsvConfig(
        path_file=Path(csv), value_column="value", date_column="date", units="m3/s"
    )
    rows, _ = build_lake_period_data(model, lakes={"lac0": {"runoff": forcing}})
    assert rows[0] == [[0, "runoff", pytest.approx(values[0])]]
