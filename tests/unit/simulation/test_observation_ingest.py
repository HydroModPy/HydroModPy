from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
import pytest

from hydromodpy.results.catalog import SimulationCatalog
from hydromodpy.simulation.extraction.extractors.observation_ingest import (
    ingest_observations,
)


@pytest.fixture
def catalog(tmp_path):
    cat = SimulationCatalog(tmp_path / "workspace")
    yield cat
    cat.close()


def _sim_id():
    return str(uuid.uuid4())


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


def _query(catalog: SimulationCatalog, sim_id: str) -> pd.DataFrame:
    return catalog._connection.execute(
        "SELECT station_id, variable, datetime, value, unit "
        "FROM timeseries WHERE sim_id = ? ORDER BY station_id, variable, datetime",
        [sim_id],
    ).fetchdf()


class TestIngest:
    def test_writes_obs_variable_with_suffix(self, catalog):
        sid = _sim_id()
        catalog.register_simulation(sid, project="obs_test", solver="modflow6")
        loaded = _StubLoadedData(
            hydrometry=_StubLoadResult(points=[_point_record("NANCON", "discharge")]),
        )

        written = ingest_observations(sid, catalog, loaded)

        assert written == 1
        rows = _query(catalog, sid)
        assert list(rows["variable"].unique()) == ["discharge_obs"]
        assert list(rows["station_id"].unique()) == ["NANCON"]
        assert len(rows) == 5
        assert rows["unit"].iloc[0] == "m3/s"

    def test_handles_multiple_managers(self, catalog):
        sid = _sim_id()
        catalog.register_simulation(sid, project="obs_test", solver="modflow6")
        loaded = _StubLoadedData(
            hydrometry=_StubLoadResult(points=[_point_record("S1", "discharge")]),
            piezometry=_StubLoadResult(points=[_point_record("S2", "water_level")]),
        )

        written = ingest_observations(sid, catalog, loaded)

        assert written == 2
        rows = _query(catalog, sid)
        variables = set(rows["variable"].unique())
        assert variables == {"discharge_obs", "water_level_obs"}

    def test_skips_missing_managers(self, catalog):
        sid = _sim_id()
        catalog.register_simulation(sid, project="obs_test", solver="modflow6")
        loaded = _StubLoadedData()

        assert ingest_observations(sid, catalog, loaded) == 0
        rows = _query(catalog, sid)
        assert rows.empty

    def test_skips_empty_dataframes(self, catalog):
        sid = _sim_id()
        catalog.register_simulation(sid, project="obs_test", solver="modflow6")
        empty_rec = _StubPointRecord(
            station_id="S1",
            variable="discharge",
            unit="m3/s",
            data=pd.DataFrame({"datetime": pd.DatetimeIndex([]), "value": []}),
        )
        loaded = _StubLoadedData(hydrometry=_StubLoadResult(points=[empty_rec]))

        assert ingest_observations(sid, catalog, loaded) == 0
        assert _query(catalog, sid).empty

    def test_run_timeseries_can_query(self, catalog):
        sid = _sim_id()
        catalog.register_simulation(sid, project="obs_test", solver="modflow6")
        loaded = _StubLoadedData(
            hydrometry=_StubLoadResult(points=[_point_record("NANCON", "discharge")]),
        )
        ingest_observations(sid, catalog, loaded)

        run = catalog[sid]
        series = run.timeseries("discharge_obs", station="NANCON")
        assert isinstance(series, pd.Series)
        assert len(series) == 5
        assert series.iloc[0] == pytest.approx(0.0)
        assert series.iloc[-1] == pytest.approx(6.0)
