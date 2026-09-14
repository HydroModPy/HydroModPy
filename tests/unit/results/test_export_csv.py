"""CSV timeseries export through DuckDB COPY: format, ordering, filters."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from hydromodpy.results.exporters.csv import export_csv

_HEADER = "datetime,station_id,variable,value,unit"


@pytest.fixture
def conn() -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect()
    conn.execute("SET TimeZone = 'UTC'")
    conn.execute(
        "CREATE TABLE timeseries ("
        "sim_id VARCHAR, station_id VARCHAR, variable VARCHAR, timestep BIGINT, "
        "time TIMESTAMPTZ, value DOUBLE, unit VARCHAR)"
    )
    conn.execute(
        "INSERT INTO timeseries VALUES "
        "('s1', 'B', 'head', 0, '2007-01-01 00:00:00+00', 2.5, 'm'), "
        "('s1', 'A', 'head', 1, '2007-01-02 00:00:00+00', 1.5, 'm'), "
        "('s1', 'A', 'head', 0, '2007-01-01 00:00:00+00', 1.0, 'm'), "
        "('s1', 'A', 'discharge', 0, NULL, 0.25, 'm3/s'), "
        "('s2', 'A', 'head', 0, '2007-01-01 00:00:00+00', 9.0, 'm')"
    )
    return conn


def test_export_orders_and_formats_like_the_pandas_path(
    conn: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    target = tmp_path / "out.csv"
    result = export_csv(conn, "s1", target)
    assert result == target
    lines = target.read_text().splitlines()
    assert lines[0] == _HEADER
    assert lines[1] == ",A,discharge,0.25,m3/s"  # NULL time stays empty
    assert lines[2] == "2007-01-01 00:00:00+00:00,A,head,1.0,m"
    assert lines[3] == "2007-01-02 00:00:00+00:00,A,head,1.5,m"
    assert lines[4] == "2007-01-01 00:00:00+00:00,B,head,2.5,m"
    assert len(lines) == 5
    parsed = pd.to_datetime(pd.read_csv(target)["datetime"], utc=True)
    assert parsed.iloc[1] == pd.Timestamp("2007-01-01", tz="UTC")


def test_export_filters_station_and_variable(
    conn: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    target = tmp_path / "filtered.csv"
    export_csv(conn, "s1", target, station_id="A", variable="head")
    lines = target.read_text().splitlines()
    assert len(lines) == 3
    assert all(",A,head," in line for line in lines[1:])


def test_export_without_rows_writes_header_only(
    conn: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    target = tmp_path / "empty.csv"
    export_csv(conn, "missing-sim", target)
    assert target.read_text().splitlines() == [_HEADER]


def test_export_creates_parent_directories(conn: duckdb.DuckDBPyConnection, tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dir" / "out.csv"
    export_csv(conn, "s2", target)
    assert target.read_text().splitlines() == [
        _HEADER,
        "2007-01-01 00:00:00+00:00,A,head,9.0,m",
    ]
