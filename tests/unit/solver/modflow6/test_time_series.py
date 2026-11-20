"""MF6 time series (TS6) tables and the lake forcing that uses them.

Times are in s from the simulation start, lake inflows and withdrawals in m3/s. A long
non-constant forcing becomes a TS6 series named in the PERIOD row, a short one is written per
period, and a managed transfer is held at zero on the steady warm-up.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import flopy
import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.exceptions import SolverInputError
from hydromodpy.core.time.window import (
    ResolvedSimulationTimeWindow,
    build_simulation_time_boundaries,
)
from hydromodpy.model.forcing.dated_forcing import CsvForcing
from hydromodpy.model.model import ModelTime
from hydromodpy.solver.modflow6.builders.lake import build_lake_period_data
from hydromodpy.solver.modflow6.builders.period_forcing import resolve_use_ts6
from hydromodpy.solver.modflow6.support.time_series import (
    Ts6Series,
    attach_time_series,
    build_ts6_table,
)
from tests._helpers.model_factory import make_model

DAY_S = 86400.0


@dataclass
class ProcessSpecific:
    lak_forcing_mode: str
    ts6_min_periods: int


@dataclass
class Config:
    process_specific: ProcessSpecific


@dataclass
class TimeGrid:
    window: ResolvedSimulationTimeWindow


class DailyModel:
    """A model of daily stress periods, with the LAK forcing mode and the TS6 threshold set."""

    def __init__(self, *, window, nper, mode, min_periods=120, steady_first=False) -> None:
        self.inputs = make_model(
            time=ModelTime(
                grid=TimeGrid(window=window), regime="transient", first_period_steady=True
            )
        )
        self.nper = nper
        self.perlen = np.full(nper, DAY_S)
        self.modflow_config = Config(ProcessSpecific(mode, min_periods))
        if steady_first:
            self.steady = (True,) + (False,) * (nper - 1)


def daily_inflow(tmp_path: Path, n_days: int, mode: str, *, flat=None, steady_first=False):
    """A daily model and the CSV forcing of its lake, whose value i is (i + 1) days of seconds."""
    start = pd.Timestamp("2003-01-01")
    window = ResolvedSimulationTimeWindow(
        start=start,
        end=start + pd.Timedelta(days=n_days),
        step_value=1,
        step_unit="day",
        coverage_policy="ignore",
    )
    starts = build_simulation_time_boundaries(window)[:-1]
    nper = len(starts)
    values = [flat if flat is not None else DAY_S * (i + 1) for i in range(nper)]
    csv = tmp_path / "inflow.csv"
    pd.DataFrame({"date": [s.date().isoformat() for s in starts], "value": values}).to_csv(
        csv, index=False
    )
    model = DailyModel(window=window, nper=nper, mode=mode, steady_first=steady_first)
    forcing = CsvForcing(path_file=csv, value_column="value", date_column="date", units="m3/s")
    return model, forcing, values


def test_ts6_table_columns() -> None:
    series = [
        Ts6Series(name="a", times=(0.0, 10.0, 20.0), values=(1.0, 2.0, 3.0)),
        Ts6Series(name="b", times=(0.0, 10.0, 20.0), values=(4.0, 5.0, 6.0)),
    ]

    timeseries, names, methods = build_ts6_table(series)

    assert names == ["a", "b"]
    assert methods == ["stepwise", "stepwise"]
    assert timeseries == [[0.0, 1.0, 4.0], [10.0, 2.0, 5.0], [20.0, 3.0, 6.0]]


def test_series_attach_to_a_wel(tmp_path: Path) -> None:
    # The helper also serves a WEL, a different package than LAK, through the shared .ts child.
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

    text = (tmp_path / "welts.wel.ts").read_text().upper()
    assert "W_RATE" in text
    assert "STEPWISE" in text
    # The WEL file references the external series by a TS6 FILEIN record.
    wel_text = (tmp_path / "welts.wel").read_text().upper()
    assert "TS6" in wel_text and "FILEIN" in wel_text


CONSTANT = {"kind": "constant", "value": 1.0}
CSV = {"kind": "csv", "path_file": "x.csv"}
USE_TS6 = [
    pytest.param(CONSTANT, "ts6", 999, False, id="constant is never routed"),
    pytest.param(CSV, "inline", 999, False, id="inline mode never routes"),
    pytest.param(CSV, "auto", 5, False, id="auto below the threshold"),
    pytest.param(CSV, "auto", 50, True, id="auto above the threshold"),
    pytest.param(CSV, "ts6", 5, True, id="ts6 mode routes any series"),
]


@pytest.mark.parametrize(("forcing", "mode", "nper", "use_ts6"), USE_TS6)
def test_use_ts6(forcing, mode, nper, use_ts6) -> None:
    assert resolve_use_ts6(forcing, mode=mode, nper=nper, min_periods=10) is use_ts6


def test_long_forcing_is_a_ts6_series(tmp_path: Path) -> None:
    model, forcing, values = daily_inflow(tmp_path, 130, "ts6")

    rows, ts_specs = build_lake_period_data(model, lakes={"lac0": {"inflow": forcing}})

    (spec,) = ts_specs
    assert spec.name == "lak0_inflow"
    assert spec.interpolation == "stepwise"
    # One breakpoint per period start plus a last one at the end, so MF6 can integrate the
    # stepwise series over the final period. The last value repeats.
    assert len(spec.times) == len(spec.values) == model.nper + 1
    assert spec.times[0] == 0.0
    assert spec.times[1] == pytest.approx(DAY_S)
    assert all(b > a for a, b in zip(spec.times, spec.times[1:]))
    assert spec.values[0] == pytest.approx(values[0])
    assert spec.values[-1] == pytest.approx(values[-1])
    # The PERIOD row names the series, the TS6 file holds the values.
    assert rows == {0: [[0, "inflow", "lak0_inflow"]]}


def test_short_forcing_is_written_per_period(tmp_path: Path) -> None:
    # Below the threshold the forcing is expanded per period, never dropped.
    model, forcing, values = daily_inflow(tmp_path, 5, "auto")

    rows, ts_specs = build_lake_period_data(model, lakes={"lac0": {"inflow": forcing}})

    assert ts_specs == []
    assert set(rows) == set(range(model.nper))
    for kper, value in enumerate(values):
        assert rows[kper] == [[0, "inflow", pytest.approx(value)]]


def test_constant_tail_is_one_row(tmp_path: Path) -> None:
    # Inline expansion emits a row only when the value changes.
    model, forcing, _ = daily_inflow(tmp_path, 4, "inline", flat=7.0)

    rows, ts_specs = build_lake_period_data(model, lakes={"lac0": {"inflow": forcing}})

    assert ts_specs == []
    assert rows == {0: [[0, "inflow", pytest.approx(7.0)]]}


def test_managed_forcing_is_zero_on_steady_warmup(tmp_path: Path) -> None:
    # A managed transfer that does not balance the natural budget has no equilibrium stage
    # without a storage term, so the steady period holds it at zero.
    model, forcing, values = daily_inflow(tmp_path, 5, "inline", steady_first=True)

    rows, _ = build_lake_period_data(model, lakes={"lac0": {"withdrawal": forcing}})

    assert rows[0] == [[0, "withdrawal", pytest.approx(0.0)]]
    for kper in range(1, model.nper):
        assert rows[kper] == [[0, "withdrawal", pytest.approx(values[kper])]]


def test_natural_forcing_stays_on_steady_warmup(tmp_path: Path) -> None:
    # Runoff is not management: the lake equilibrates under real hydrology.
    model, forcing, values = daily_inflow(tmp_path, 5, "inline", steady_first=True)

    rows, _ = build_lake_period_data(model, lakes={"lac0": {"runoff": forcing}})

    assert rows[0] == [[0, "runoff", pytest.approx(values[0])]]


def has_status_row(rows) -> bool:
    return any(row[1] == "status" for period in rows.values() for row in period)


def test_steady_stage_hold(tmp_path: Path) -> None:
    # The steady warm-up holds the stage at initial_stage (CONSTANT), the lake is ACTIVE after.
    model, _, _ = daily_inflow(tmp_path, 4, "inline", steady_first=True)

    rows, _ = build_lake_period_data(
        model, lakes={"lac0": {"steady_stage_hold": True, "initial_stage": 81.82}}
    )

    assert [0, "status", "CONSTANT"] in rows[0]
    assert [0, "status", "ACTIVE"] in rows[1]


def test_no_stage_hold_without_opt_in_or_steady(tmp_path: Path, caplog) -> None:
    model, _, _ = daily_inflow(tmp_path, 4, "inline", steady_first=True)
    with caplog.at_level(logging.WARNING):
        rows, _ = build_lake_period_data(model, lakes={"lac0": {"initial_stage": 81.82}})
    assert not has_status_row(rows)
    # The steady solve overrides initial_stage, and the build says so.
    assert "only its first guess" in caplog.text
    assert "81.82" in caplog.text

    model.steady = (False,) * model.nper
    rows, _ = build_lake_period_data(
        model, lakes={"lac0": {"steady_stage_hold": True, "initial_stage": 81.82}}
    )
    assert not has_status_row(rows)


TS6_REFUSALS = [
    pytest.param(
        [
            Ts6Series(name="a", times=(0.0, 10.0), values=(1.0, 2.0)),
            Ts6Series(name="b", times=(0.0, 20.0), values=(3.0, 4.0)),
        ],
        "same time axis",
        id="mismatched axes",
    ),
    pytest.param(
        [
            Ts6Series(name="dup", times=(0.0, 10.0), values=(1.0, 2.0)),
            Ts6Series(name="dup", times=(0.0, 10.0), values=(3.0, 4.0)),
        ],
        "unique",
        id="name collision",
    ),
    pytest.param(
        [Ts6Series(name="a", times=(0.0, 0.0), values=(1.0, 2.0))],
        "strictly increasing",
        id="times not increasing",
    ),
]


@pytest.mark.parametrize(("series", "message"), TS6_REFUSALS)
def test_ts6_table_refusals(series, message) -> None:
    with pytest.raises(SolverInputError, match=message):
        build_ts6_table(series)
