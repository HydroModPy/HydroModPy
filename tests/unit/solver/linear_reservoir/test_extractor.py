"""Rows the linear reservoir extractor writes to the run store, read back.

The discharge (m3/s) and the storage depth (m) go to the catchment station. The budget rows
of each period, in m3, close to zero.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.exceptions import NothingThereError
from hydromodpy.core.scope import CATCHMENT
from hydromodpy.solver.linear_reservoir.adapter import SERIES_FILE, LinearReservoir, _series_frame
from hydromodpy.solver.linear_reservoir.extractor import LinearReservoirExtractor

TAU_SECONDS = 30.0 * 86400.0
AREA_M2 = 1.0e6


class StoreDouble:
    """The few members of the run store the extractor writes with."""

    sim_id = "sim-one"

    def __init__(self) -> None:
        self.timeseries: list[tuple] = []
        self.budgets: list[dict] = []

    def write_time(self, sim_id, axis, *, epoch=None, units=None):
        pass

    def write_timeseries(self, sim_id, station_id, variable, ts, unit="", source="simulated"):
        self.timeseries.append((sim_id, station_id, variable, ts, unit, source))

    def write_budgets(self, sim_id, records):
        self.budgets.extend(records)


def two_days_of_recharge(tmp_path) -> StoreDouble:
    """Run the reservoir for two days at 5e-8 m/s and extract it into a store."""
    lengths = (86400.0, 86400.0)
    engine = LinearReservoir(
        tau_seconds=TAU_SECONDS,
        area_m2=AREA_M2,
        rates_m_per_s=(5.0e-8, 5.0e-8),
        durations_s=lengths,
        owner_of_piece=(0, 1),
        period_lengths_s=lengths,
    )
    states_stored, drained_depths = engine.run()
    frame = _series_frame(engine, states_stored, drained_depths)
    frame.to_csv(tmp_path / SERIES_FILE, index_label="time")
    grid = SimpleNamespace(
        window=None,
        boundaries=(pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-02")),
        period_lengths_seconds=lengths,
    )
    run = SimpleNamespace(
        sim_id=None,
        output_dir=tmp_path,
        model=SimpleNamespace(time=SimpleNamespace(grid=grid)),
        solver_model=engine,
    )
    store = StoreDouble()
    LinearReservoirExtractor().extract(run, store, SimpleNamespace())
    return store


def test_discharge_and_storage_at_the_catchment(tmp_path) -> None:
    store = two_days_of_recharge(tmp_path)

    assert {item[2] for item in store.timeseries} == {"discharge", "reservoir_storage"}
    assert {item[1] for item in store.timeseries} == {CATCHMENT}
    assert {item[2]: item[4] for item in store.timeseries} == {
        "discharge": "m3 s-1",
        "reservoir_storage": "m",
    }


def test_budget_rows_of_a_period_close(tmp_path) -> None:
    # Recharge is an inflow, the drain an outflow, and storage is -A ds/dt in the sign of
    # core/budget, so the three terms of one period sum to zero.
    store = two_days_of_recharge(tmp_path)

    per_period: dict[int, list[dict]] = {}
    for record in store.budgets:
        per_period.setdefault(record["timestep"], []).append(record)

    assert sorted(per_period) == [0, 1]
    for step, records in per_period.items():
        net = sum(rec["flux_in"] - rec["flux_out"] for rec in records)
        assert net == pytest.approx(0.0, abs=1e-12), f"period {step} leaves {net} open"


PERIOD_ROWS = (
    "time,recharge_m_s,discharge_m3_s,reservoir_storage_m\n"
    "2024-01-02,5e-8,0.05,0.1\n"
    "2024-01-03,5e-8,0.05,0.1\n"
)


class StoreWithoutTime(StoreDouble):
    write_time = None


def run_of(output_dir, lengths) -> SimpleNamespace:
    grid = SimpleNamespace(
        window=None,
        boundaries=(pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-03")),
        period_lengths_seconds=lengths,
    )
    return SimpleNamespace(
        output_dir=output_dir,
        model=SimpleNamespace(time=SimpleNamespace(grid=grid)),
        solver_model=SimpleNamespace(area_m2=AREA_M2, initial_depth_m=0.1),
    )


EXTRACTION_REFUSALS = [
    pytest.param(
        "time,recharge_m_s,discharge_m3_s,reservoir_storage_m\n",
        (86400.0, 86400.0),
        StoreDouble(),
        "holds no period",
        id="empty series",
    ),
    pytest.param(
        PERIOD_ROWS,
        (86400.0, 86400.0),
        StoreWithoutTime(),
        "must implement write_time",
        id="store without a time axis",
    ),
    pytest.param(
        PERIOD_ROWS,
        (86400.0,),
        StoreDouble(),
        "1 periods of the time grid and 2 rows",
        id="short grid",
    ),
    pytest.param(
        PERIOD_ROWS,
        None,
        StoreDouble(),
        "0 periods of the time grid and 2 rows",
        id="no period lengths",
    ),
]


@pytest.mark.parametrize(("text", "lengths", "store", "message"), EXTRACTION_REFUSALS)
def test_extraction_refusals(tmp_path, text, lengths, store, message) -> None:
    (tmp_path / SERIES_FILE).write_text(text, encoding="utf-8")

    with pytest.raises((NothingThereError, TypeError), match=message):
        LinearReservoirExtractor().extract(run_of(tmp_path, lengths), store, SimpleNamespace())


def test_extraction_needs_the_series_file(tmp_path) -> None:
    with pytest.raises(NothingThereError, match=f"No {SERIES_FILE} in"):
        LinearReservoirExtractor().extract(
            run_of(tmp_path, (86400.0,)), StoreDouble(), SimpleNamespace()
        )
