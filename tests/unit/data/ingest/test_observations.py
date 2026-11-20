"""Observed series of a run: station chronicles (m3/s, daily) written to the run store."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import pytest

from hydromodpy.data.ingest.observations import ingest_observations
from hydromodpy.results.storage.run_store import RunStore
from tests._helpers.run_builders import runs

__all__ = ["runs"]


@dataclass
class _StubPointRecord:
    station_id: str
    variable: str
    unit: str
    data: pd.DataFrame


@dataclass
class _StubLoadResult:
    points: list = field(default_factory=list)


@dataclass
class _StubLoadedData:
    hydrometry: Any = None
    piezometry: Any = None
    intermittency: Any = None
    water_quality: Any = None
    recharge: Any = None


def _point_record(station_id: str, variable: str, n_points: int = 5) -> _StubPointRecord:
    dates = pd.date_range("2000-01-01", periods=n_points, freq="D")
    values = np.arange(n_points, dtype="float64") * 1.5
    return _StubPointRecord(
        station_id=station_id,
        variable=variable,
        unit="m3/s",
        data=pd.DataFrame({"datetime": dates, "value": values}),
    )


def _query(store: RunStore) -> pd.DataFrame:
    """The series rows the run wrote, read from its own ``timeseries`` table."""
    frame = store.read_table("timeseries")
    if frame.empty:
        return frame
    return frame.sort_values(["station_id", "variable", "timestep"], ignore_index=True)


def test_two_variables_written(runs):
    store = runs.open()
    loaded = _StubLoadedData(
        hydrometry=_StubLoadResult(points=[_point_record("S1", "discharge")]),
        piezometry=_StubLoadResult(points=[_point_record("S2", "water_level")]),
    )

    written = ingest_observations(store.sim_id, store, loaded)

    assert written == 2
    assert set(_query(store)["variable"].unique()) == {"discharge", "water_level"}


def test_empty_chronicle_skipped(runs):
    store = runs.open()
    empty = _StubPointRecord(
        station_id="S1",
        variable="discharge",
        unit="m3/s",
        data=pd.DataFrame({"datetime": pd.DatetimeIndex([]), "value": []}),
    )
    loaded = _StubLoadedData(hydrometry=_StubLoadResult(points=[empty]))

    assert ingest_observations(store.sim_id, store, loaded) == 0
    assert _query(store).empty


def test_run_answers_timeseries(runs):
    store = runs.open()
    loaded = _StubLoadedData(
        hydrometry=_StubLoadResult(points=[_point_record("NANCON", "discharge")]),
    )
    ingest_observations(store.sim_id, store, loaded)

    run = runs.catalog()[store.sim_id]
    series = run.timeseries("discharge", station="NANCON", source="observed")

    assert isinstance(series, pd.Series)
    assert len(series) == 5
    assert series.iloc[0] == pytest.approx(0.0)
    assert series.iloc[-1] == pytest.approx(6.0)  # 4 steps x 1.5
