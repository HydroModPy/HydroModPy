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


class TestIngest:
    def test_writes_the_variable_as_observed(self, runs):
        store = runs.open()
        sid = store.sim_id
        loaded = _StubLoadedData(
            hydrometry=_StubLoadResult(points=[_point_record("NANCON", "discharge")]),
        )

        written = ingest_observations(sid, store, loaded)

        assert written == 1
        rows = _query(store)
        assert list(rows["variable"].unique()) == ["discharge"]
        assert list(rows["station_id"].unique()) == ["NANCON"]
        assert len(rows) == 5
        assert rows["unit"].iloc[0] == "m3 s-1"
        assert rows["source"].unique().tolist() == ["observed"]
        assert rows["value"].iloc[0] == 0.0

    def test_handles_multiple_managers(self, runs):
        store = runs.open()
        sid = store.sim_id
        loaded = _StubLoadedData(
            hydrometry=_StubLoadResult(points=[_point_record("S1", "discharge")]),
            piezometry=_StubLoadResult(points=[_point_record("S2", "water_level")]),
        )

        written = ingest_observations(sid, store, loaded)

        assert written == 2
        rows = _query(store)
        variables = set(rows["variable"].unique())
        assert variables == {"discharge", "water_level"}

    def test_skips_missing_managers(self, runs):
        store = runs.open()
        sid = store.sim_id
        loaded = _StubLoadedData()

        assert ingest_observations(sid, store, loaded) == 0
        rows = _query(store)
        assert rows.empty

    def test_skips_empty_dataframes(self, runs):
        store = runs.open()
        sid = store.sim_id
        empty_rec = _StubPointRecord(
            station_id="S1",
            variable="discharge",
            unit="m3/s",
            data=pd.DataFrame({"datetime": pd.DatetimeIndex([]), "value": []}),
        )
        loaded = _StubLoadedData(hydrometry=_StubLoadResult(points=[empty_rec]))

        assert ingest_observations(sid, store, loaded) == 0
        assert _query(store).empty

    def test_run_timeseries_can_query(self, runs):
        store = runs.open()
        sid = store.sim_id
        loaded = _StubLoadedData(
            hydrometry=_StubLoadResult(points=[_point_record("NANCON", "discharge")]),
        )
        ingest_observations(sid, store, loaded)

        run = runs.catalog()[sid]
        series = run.timeseries("discharge", station="NANCON", source="observed")
        assert isinstance(series, pd.Series)
        assert len(series) == 5
        assert series.iloc[0] == pytest.approx(0.0)
        assert series.iloc[-1] == pytest.approx(6.0)
