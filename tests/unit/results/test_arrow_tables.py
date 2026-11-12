"""Columnar timeseries write path: table_from_columns and write_timeseries_columns.

A column is a per-row array or a scalar repeated on every row. Times are UTC, flows in m3/s.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.results.storage.arrow_tables import table_from_columns
from hydromodpy.results.storage.parquet_schemas import TIMESERIES_SCHEMA
from tests._helpers.run_stores import open_run_store

REFUSALS = [
    pytest.param({"bogus": np.ones(2)}, {}, "not in schema", id="unknown column"),
    pytest.param(
        {"timestep": np.arange(3), "value": np.ones(2), "variable": "q"},
        {"sim_id": "s"},
        "rows",
        id="length mismatch",
    ),
    pytest.param({"variable": "q"}, {}, "per-row array", id="scalars only"),
]


@pytest.mark.parametrize(("columns", "defaults", "match"), REFUSALS)
def test_refused_columns(columns, defaults, match) -> None:
    with pytest.raises(ValueError, match=match):
        table_from_columns(columns, TIMESERIES_SCHEMA, defaults=defaults)


def test_columns_match_the_batch_writer(tmp_path: Path) -> None:
    n = 4
    times = np.array([f"2020-01-{2 + i:02d}T00:00:00" for i in range(n)], dtype="datetime64[ms]")
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


def test_empty_columns_write_nothing(tmp_path: Path) -> None:
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
