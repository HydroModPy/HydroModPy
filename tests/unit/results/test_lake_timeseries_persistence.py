"""Per-lake LAK series persist into the ResultStore keyed (lake_id, totim).

The per-lake series reuse the existing TIMESERIES_SCHEMA with
``station_id = lake:<id>``, so the primary key ``(sim_id, station_id, variable,
timestep)`` already encodes ``(lake_id, totim)`` and needs no schema migration.
The test round-trips a batch of lake records through the store of a run, then
through the index once the run is sealed, and asserts the query returns them and
that the PK de-duplicates a re-write of the same ``(lake_id, variable, timestep)``.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.solver.modflow6.extractors.lake import lake_station_id
from tests._helpers.run_stores import open_run_store


def _store(project: Path, name: str = "lake_sim") -> RunStore:
    return open_run_store(project, name, create_zarr=False)


def _lake_records(station: str) -> list[dict]:
    base = pd.Timestamp("2020-01-01", tz="UTC")
    records: list[dict] = []
    for t, (stage, exchange) in enumerate([(95.0, -0.5), (94.0, -0.4), (93.5, -0.3)]):
        time = base + pd.Timedelta(days=t)
        records.append(
            {
                "station_id": station,
                "variable": "stage",
                "timestep": t,
                "time": time,
                "value": stage,
                "unit": "m",
                "source": "simulated",
            }
        )
        records.append(
            {
                "station_id": station,
                "variable": "gwf_exchange",
                "timestep": t,
                "time": time,
                "value": exchange,
                "unit": "m3/s",
                "source": "simulated",
            }
        )
    return records


def test_round_trip(tmp_path: Path) -> None:
    station = lake_station_id("lac0")
    with _store(tmp_path) as store:
        sid = store.sim_id
        store.write_timeseries_batch(sid, _lake_records(station))

        stage = store.query_timeseries(sid, station, "stage")
        exchange = store.query_timeseries(sid, station, "gwf_exchange")

    assert list(stage.values) == pytest.approx([95.0, 94.0, 93.5])
    # The lake-aquifer exchange is negative at every step (lake losing water).
    assert all(value < 0.0 for value in exchange.values)
    assert list(exchange.values) == pytest.approx([-0.5, -0.4, -0.3])


def test_primary_key_dedupes(tmp_path: Path) -> None:
    station = lake_station_id("lac0")
    store = _store(tmp_path)
    sid = store.sim_id
    store.write_timeseries_batch(sid, _lake_records(station))
    # Re-write the same (lake, variable, timestep) with corrected stages: the
    # PK (sim_id, station_id, variable, timestep) must overwrite, not append.
    corrected = [
        dict(record, value=record["value"] + 1.0)
        for record in _lake_records(station)
        if record["variable"] == "stage"
    ]
    store.write_timeseries_batch(sid, corrected)
    seal_completed(store)
    rebuild_index(tmp_path)

    with Catalog(tmp_path) as cat:
        count = cat.connection.execute(
            "SELECT COUNT(*) FROM timeseries WHERE sim_id = ? AND station_id = ? "
            "AND variable = 'stage'",
            [sid, station],
        ).fetchone()[0]
        stage = cat.query_timeseries(sid, station, "stage")

    # Three timesteps, not six: the re-write replaced the rows in place.
    assert count == 3
    assert list(stage.values) == pytest.approx([96.0, 95.0, 94.5])
