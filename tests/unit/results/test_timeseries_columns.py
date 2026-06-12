"""Columnar timeseries write path: _table_from_columns + write_timeseries_columns."""

from __future__ import annotations

import uuid
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.writes_helpers import _table_from_columns, _table_from_records
from hydromodpy.results.parquet_schemas import TIMESERIES_SCHEMA


def _register(catalog: Catalog, name: str = "sim") -> str:
    sid = str(uuid.uuid4())
    catalog.register_simulation(sid, project="p", solver="modflow6", name=name)
    return sid


class TestTableFromColumns:
    def test_matches_record_built_table(self) -> None:
        times = np.array(["2020-01-01", "2020-01-02", "2020-01-03"], dtype="datetime64[ms]")
        records = [
            {
                "sim_id": "s",
                "station_id": f"P{i}",
                "variable": "head",
                "timestep": i,
                "time": pd.Timestamp(times[i]).tz_localize("UTC"),
                "value": float(i),
                "unit": "m",
                "qflag": "simulated",
            }
            for i in range(3)
        ]
        from_records = _table_from_records(records, TIMESERIES_SCHEMA)
        from_columns = _table_from_columns(
            {
                "station_id": np.array([f"P{i}" for i in range(3)], dtype=object),
                "variable": "head",
                "timestep": np.arange(3, dtype="int64"),
                "time": times,
                "value": np.arange(3, dtype="float64"),
                "unit": "m",
                "qflag": "simulated",
            },
            TIMESERIES_SCHEMA,
            defaults={"sim_id": "s"},
        )
        assert from_columns.schema.equals(from_records.schema)
        assert from_columns.equals(from_records)

    def test_missing_columns_default_or_null(self) -> None:
        table = _table_from_columns(
            {"variable": "q", "timestep": np.arange(2), "value": np.ones(2)},
            TIMESERIES_SCHEMA,
            defaults={"sim_id": "s", "unit": "", "qflag": "simulated"},
        )
        assert table.column("station_id").null_count == 2
        assert table.column("time").null_count == 2
        assert table.column("unit").to_pylist() == ["", ""]
        assert table.column("qflag").to_pylist() == ["simulated", "simulated"]

    def test_unknown_column_raises(self) -> None:
        with pytest.raises(ValueError, match="not in schema"):
            _table_from_columns({"bogus": np.ones(2)}, TIMESERIES_SCHEMA)

    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="rows"):
            _table_from_columns(
                {"timestep": np.arange(3), "value": np.ones(2), "variable": "q"},
                TIMESERIES_SCHEMA,
                defaults={"sim_id": "s"},
            )

    def test_scalar_only_raises(self) -> None:
        with pytest.raises(ValueError, match="per-row array"):
            _table_from_columns({"variable": "q"}, TIMESERIES_SCHEMA)


class TestWriteTimeseriesColumns:
    def test_roundtrip_and_parity_with_batch(self, tmp_path: Path) -> None:
        n = 4
        times = np.array(
            [f"2020-01-{2 + i:02d}T00:00:00" for i in range(n)], dtype="datetime64[ms]"
        )
        with Catalog(tmp_path) as cat:
            sid_cols = _register(cat, name="cols")
            cat.write_timeseries_columns(
                sid_cols,
                {
                    "station_id": np.full(n, "sfr:net0:3", dtype=object),
                    "variable": "downstream_flow",
                    "timestep": np.arange(n, dtype="int64"),
                    "time": times,
                    "value": np.linspace(1.0, 4.0, n),
                    "unit": "m3/s",
                },
            )
            sid_batch = _register(cat, name="batch")
            cat.write_timeseries_batch(
                sid_batch,
                [
                    {
                        "station_id": "sfr:net0:3",
                        "variable": "downstream_flow",
                        "timestep": i,
                        "time": pd.Timestamp(times[i]).tz_localize("UTC"),
                        "value": float(np.linspace(1.0, 4.0, n)[i]),
                        "unit": "m3/s",
                    }
                    for i in range(n)
                ],
            )
            query = (
                "SELECT station_id, variable, timestep, time, value, unit, qflag "
                "FROM timeseries WHERE sim_id = ? ORDER BY timestep"
            )
            df_cols = cat.connection.execute(query, [sid_cols]).df()
            df_batch = cat.connection.execute(query, [sid_batch]).df()
        pd.testing.assert_frame_equal(df_cols, df_batch)
        assert df_cols["qflag"].tolist() == ["simulated"] * n
        assert df_cols["value"].tolist() == pytest.approx([1.0, 2.0, 3.0, 4.0])

    def test_last_write_wins_merge(self, tmp_path: Path) -> None:
        with Catalog(tmp_path) as cat:
            sid = _register(cat)
            base = {
                "station_id": "P1",
                "variable": "head",
                "timestep": np.arange(3, dtype="int64"),
            }
            cat.write_timeseries_columns(sid, {**base, "value": np.zeros(3)})
            cat.write_timeseries_columns(
                sid, {**base, "timestep": np.arange(1, 3, dtype="int64"), "value": np.ones(2)}
            )
            rows = cat.connection.execute(
                "SELECT timestep, value FROM timeseries WHERE sim_id = ? ORDER BY timestep",
                [sid],
            ).fetchall()
        assert rows == [(0, 0.0), (1, 1.0), (2, 1.0)]

    def test_empty_columns_are_a_noop(self, tmp_path: Path) -> None:
        with Catalog(tmp_path) as cat:
            sid = _register(cat)
            cat.write_timeseries_columns(sid, {})
            cat.write_timeseries_columns(
                sid,
                {
                    "station_id": np.array([], dtype=object),
                    "variable": np.array([], dtype=object),
                    "timestep": np.array([], dtype="int64"),
                    "value": np.array([], dtype="float64"),
                },
            )
            count = cat.connection.execute(
                "SELECT COUNT(*) FROM timeseries WHERE sim_id = ?", [sid]
            ).fetchone()[0]
        assert count == 0
