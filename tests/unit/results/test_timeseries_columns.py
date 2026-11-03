"""Columnar timeseries write path: table_from_columns and write_timeseries_columns."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.results.storage.arrow_tables import table_from_columns, table_from_records
from hydromodpy.results.storage.parquet_schemas import TIMESERIES_SCHEMA
from tests._helpers.run_stores import open_run_store


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
                "source": "simulated",
            }
            for i in range(3)
        ]
        from_records = table_from_records(records, TIMESERIES_SCHEMA)
        from_columns = table_from_columns(
            {
                "station_id": np.array([f"P{i}" for i in range(3)], dtype=object),
                "variable": "head",
                "timestep": np.arange(3, dtype="int64"),
                "time": times,
                "value": np.arange(3, dtype="float64"),
                "unit": "m",
                "source": "simulated",
            },
            TIMESERIES_SCHEMA,
            defaults={"sim_id": "s"},
        )
        assert from_columns.schema.equals(from_records.schema)
        assert from_columns.equals(from_records)

    def test_missing_columns_default_or_null(self) -> None:
        table = table_from_columns(
            {"variable": "q", "timestep": np.arange(2), "value": np.ones(2)},
            TIMESERIES_SCHEMA,
            defaults={"sim_id": "s", "unit": "", "source": "simulated"},
        )
        assert table.column("station_id").null_count == 2
        assert table.column("time").null_count == 2
        assert table.column("unit").to_pylist() == ["", ""]
        assert table.column("source").to_pylist() == ["simulated", "simulated"]

    def test_unknown_column_raises(self) -> None:
        with pytest.raises(ValueError, match="not in schema"):
            table_from_columns({"bogus": np.ones(2)}, TIMESERIES_SCHEMA)

    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="rows"):
            table_from_columns(
                {"timestep": np.arange(3), "value": np.ones(2), "variable": "q"},
                TIMESERIES_SCHEMA,
                defaults={"sim_id": "s"},
            )

    def test_scalar_only_raises(self) -> None:
        with pytest.raises(ValueError, match="per-row array"):
            table_from_columns({"variable": "q"}, TIMESERIES_SCHEMA)


class TestWriteTimeseriesColumns:
    def test_roundtrip_and_parity_with_batch(self, tmp_path: Path) -> None:
        n = 4
        times = np.array(
            [f"2020-01-{2 + i:02d}T00:00:00" for i in range(n)], dtype="datetime64[ms]"
        )
        with open_run_store(tmp_path / "p", "cols") as cols:
            cols.write_timeseries_columns(
                cols.sim_id,
                {
                    "station_id": np.full(n, "sfr:net0:3", dtype=object),
                    "variable": "downstream_flow",
                    "timestep": np.arange(n, dtype="int64"),
                    "time": times,
                    "value": np.linspace(1.0, 4.0, n),
                    "unit": "m3/s",
                },
            )
            df_cols = cols.read_table("timeseries").drop(columns=["sim_id"])
        with open_run_store(tmp_path / "p", "batch") as batch:
            batch.write_timeseries_batch(
                batch.sim_id,
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
            df_batch = batch.read_table("timeseries").drop(columns=["sim_id"])
        pd.testing.assert_frame_equal(
            df_cols.sort_values("timestep").reset_index(drop=True),
            df_batch.sort_values("timestep").reset_index(drop=True),
        )
        assert df_cols["source"].tolist() == ["simulated"] * n
        assert sorted(df_cols["value"].tolist()) == pytest.approx([1.0, 2.0, 3.0, 4.0])

    def test_last_write_wins_merge(self, tmp_path: Path) -> None:
        with open_run_store(tmp_path / "p") as store:
            base = {
                "station_id": "P1",
                "variable": "head",
                "timestep": np.arange(3, dtype="int64"),
            }
            store.write_timeseries_columns(store.sim_id, {**base, "value": np.zeros(3)})
            store.write_timeseries_columns(
                store.sim_id,
                {**base, "timestep": np.arange(1, 3, dtype="int64"), "value": np.ones(2)},
            )
            frame = store.read_table("timeseries").sort_values("timestep")
        assert list(zip(frame["timestep"], frame["value"], strict=True)) == [
            (0, 0.0),
            (1, 1.0),
            (2, 1.0),
        ]

    def test_empty_columns_are_a_noop(self, tmp_path: Path) -> None:
        with open_run_store(tmp_path / "p") as store:
            store.write_timeseries_columns(store.sim_id, {})
            store.write_timeseries_columns(
                store.sim_id,
                {
                    "station_id": np.array([], dtype=object),
                    "variable": np.array([], dtype=object),
                    "timestep": np.array([], dtype="int64"),
                    "value": np.array([], dtype="float64"),
                },
            )
            assert store.read_table("timeseries").empty
