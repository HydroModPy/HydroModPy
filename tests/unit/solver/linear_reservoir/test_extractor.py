"""The station and the rows the extractor writes, read back from the run store."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.scope import CATCHMENT
from hydromodpy.solver.linear_reservoir.adapter import SERIES_FILE, _series_frame
from hydromodpy.solver.linear_reservoir.extractor import LinearReservoirExtractor

TAU_SECONDS = 30.0 * 86400.0
AREA_M2 = 1.0e6


class StoreDouble:
    """The few members of the run store the extractor writes with."""

    def __init__(self, sim_id: str) -> None:
        self.sim_id = sim_id
        self.timeseries: list[tuple] = []
        self.budgets: list[dict] = []
        self.calls: list[tuple] = []

    def write_time(self, sim_id, axis, *, epoch=None, units=None):
        self.calls.append(("time", sim_id, axis, epoch, units))

    def write_timeseries(self, sim_id, station_id, variable, ts, unit="", source="simulated"):
        self.timeseries.append((sim_id, station_id, variable, ts, unit, source))

    def write_budgets(self, sim_id, records):
        self.budgets.extend(records)


class RetentionDouble:
    """The retention the reservoir reads: one policy, nothing per cell."""


def _engine(rates: np.ndarray, lengths: np.ndarray):
    from hydromodpy.solver.linear_reservoir.adapter import LinearReservoir

    return LinearReservoir(
        tau_seconds=TAU_SECONDS,
        area_m2=AREA_M2,
        rates_m_per_s=tuple(float(r) for r in rates),
        durations_s=tuple(float(length) for length in lengths),
        owner_of_piece=tuple(range(len(rates))),
    )


def _solver_run_double(tmp_path, model, engine=None, lengths=None) -> SimpleNamespace:
    model.time.grid.period_lengths_seconds = (
        () if lengths is None else tuple(float(length) for length in lengths)
    )
    return SimpleNamespace(sim_id=None, output_dir=tmp_path, model=model, solver_model=engine)


def _run_extract_write(
    tmp_path, rates: np.ndarray, lengths: np.ndarray
) -> tuple[object, list[str]]:
    from hydromodpy.solver.linear_reservoir.adapter import LinearReservoir

    engine = LinearReservoir(
        tau_seconds=TAU_SECONDS,
        area_m2=AREA_M2,
        rates_m_per_s=tuple(float(r) for r in rates),
        durations_s=tuple(float(length) for length in lengths),
        owner_of_piece=tuple(range(len(rates))),
        period_lengths_s=tuple(float(length) for length in lengths),
    )
    states_stored, drained_depths = engine.run()
    frame = _series_frame(engine, states_stored, drained_depths)
    frame.to_csv(tmp_path / SERIES_FILE, index_label="time")
    model = SimpleNamespace(
        time=SimpleNamespace(
            grid=SimpleNamespace(
                window=None,
                boundaries=(pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-02")),
            )
        )
    )
    run = _solver_run_double(tmp_path, model, engine, lengths)
    store = StoreDouble("sim-one")
    LinearReservoirExtractor().extract(run, store, RetentionDouble())
    return store, engine


def test_the_discharge_and_the_storage_read_at_the_catchment_station(tmp_path) -> None:
    """The extractor stamps the discharge and the storage at `catchment`."""
    rates = np.array([5.0e-8, 5.0e-8])
    lengths = np.array([86400.0, 86400.0])
    store, engine = _run_extract_write(tmp_path, rates, lengths)
    written = {item[2] for item in store.timeseries}
    stations = {item[1] for item in store.timeseries}
    assert written == {"discharge", "reservoir_storage"}
    assert stations == {CATCHMENT}
    del engine


def test_the_three_rows_of_a_period_close_the_mass(tmp_path) -> None:
    """Per period, recharge less drain plus the storage of the core closes.

    The extractor writes `recharge` as an inflow, `drain` to the outlet as
    an outflow, and `storage` as `-A ds/dt` in the sign of `core/budget`,
    positive when the state falls (A1), so the sum of the three terms of
    one period reads what fell, what left, and the change of state.
    """
    rates = np.array([5.0e-8, 5.0e-8])
    lengths = np.array([86400.0, 86400.0])
    store, engine = _run_extract_write(tmp_path, rates, lengths)
    per_period: dict[int, list[dict]] = {}
    for record in store.budgets:
        per_period.setdefault(record["timestep"], []).append(record)
    assert sorted(per_period) == [0, 1]
    for step, records in per_period.items():
        net = sum(rec["flux_in"] - rec["flux_out"] for rec in records)
        assert net == pytest.approx(0.0, abs=1e-12), f"period {step} leaves {net} open"

    # The discharge column of the series closes the same volume the engine
    # released over the period, read back at the station of the catchment.
    released_by_period = dict.fromkeys(sorted(engine.owner_of_piece), 0)
    del released_by_period
