"""CSV timeseries export through DuckDB COPY: format, ordering, filters, windows."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from hydromodpy.results.exporters.csv import export_budget_csv, export_csv

_HEADER = "datetime,station_id,variable,value,unit"


@pytest.fixture
def conn() -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect()
    # A session zone east of Greenwich: the file must not be shifted by it.
    conn.execute("SET TimeZone = 'Europe/Paris'")
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


def test_export_orders_and_writes_naive_times_of_the_run_clock(
    conn: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    target = tmp_path / "out.csv"
    result = export_csv(conn, "s1", target)
    assert result == target
    lines = target.read_text().splitlines()
    assert lines[0] == _HEADER
    assert lines[1] == ",A,discharge,0.25,m3/s"  # NULL time stays empty
    assert lines[2] == "2007-01-01 00:00:00,A,head,1.0,m"
    assert lines[3] == "2007-01-02 00:00:00,A,head,1.5,m"
    assert lines[4] == "2007-01-01 00:00:00,B,head,2.5,m"
    assert len(lines) == 5
    parsed = pd.to_datetime(pd.read_csv(target)["datetime"])
    assert parsed.iloc[1] == pd.Timestamp("2007-01-01")


def test_export_filters_station_and_variables(
    conn: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    target = tmp_path / "filtered.csv"
    export_csv(conn, "s1", target, station_id="A", variables=["head"])
    lines = target.read_text().splitlines()
    assert len(lines) == 3
    assert all(",A,head," in line for line in lines[1:])


def test_export_keeps_every_variable_listed(
    conn: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    target = tmp_path / "both.csv"
    export_csv(conn, "s1", target, station_id="A", variables=["head", "discharge"])
    assert set(pd.read_csv(target)["variable"]) == {"head", "discharge"}


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
        "2007-01-01 00:00:00,A,head,9.0,m",
    ]


def test_the_catchment_sentinel_is_renamed(tmp_path: Path) -> None:
    conn = duckdb.connect()
    conn.execute(
        "CREATE TABLE timeseries (sim_id VARCHAR, station_id VARCHAR, variable VARCHAR, "
        "timestep BIGINT, time TIMESTAMPTZ, value DOUBLE, unit VARCHAR)"
    )
    conn.execute(
        "INSERT INTO timeseries VALUES "
        "('s', '_catchment', 'discharge', 0, '2000-02-01 00:00:00+00', 1.0, 'm3/s')"
    )
    target = tmp_path / "q.csv"
    export_csv(conn, "s", target)
    assert target.read_text().splitlines()[1] == "2000-02-01 00:00:00,catchment,discharge,1.0,m3/s"


def test_no_window_keeps_no_row(conn: duckdb.DuckDBPyConnection, tmp_path: Path) -> None:
    """An empty window list is a valid filter, not a SQL syntax error."""
    target = tmp_path / "none.csv"
    export_csv(conn, "s1", target, windows=[])
    assert target.read_text().splitlines() == [_HEADER]


def test_a_window_keeps_simulated_ends_and_observed_starts(tmp_path: Path) -> None:
    """A simulated value closes its period, an observation opens its day."""
    conn = duckdb.connect()
    conn.execute(
        "CREATE TABLE timeseries (sim_id VARCHAR, station_id VARCHAR, variable VARCHAR, "
        "timestep BIGINT, time TIMESTAMPTZ, value DOUBLE, unit VARCHAR)"
    )
    conn.execute(
        "INSERT INTO timeseries VALUES "
        "('s', 'c', 'discharge', 0, '2000-02-01 00:00:00+00', 1.0, 'm3/s'), "
        "('s', 'c', 'discharge', 1, '2000-03-01 00:00:00+00', 2.0, 'm3/s'), "
        "('s', 'g', 'discharge_obs', 0, '2000-01-31 00:00:00+00', 7.0, 'm3/s'), "
        "('s', 'g', 'discharge_obs', 1, '2000-02-01 00:00:00+00', 8.0, 'm3/s'), "
        "('s', 'g', 'discharge_obs', 2, '2000-03-01 00:00:00+00', 9.0, 'm3/s')"
    )
    target = tmp_path / "feb.csv"
    window = (pd.Timestamp("2000-02-01"), pd.Timestamp("2000-03-01"))
    export_csv(conn, "s", target, windows=[window])
    frame = pd.read_csv(target)
    assert frame["value"].tolist() == [2.0, 8.0]


def test_the_budget_names_each_period_it_covers(tmp_path: Path) -> None:
    budget = pd.DataFrame(
        {
            "sim_id": ["s"] * 3,
            "timestep": [1, 0, 1],
            "zone_id": ["z", "z", "z"],
            "component": ["recharge", "recharge", "drain"],
            "flux_in": [2.0, 1.0, 0.0],
            "flux_out": [0.0, 0.0, 0.5],
            "unit": ["m3/s"] * 3,
        }
    )
    edges = list(pd.to_datetime(["2000-01-01", "2000-02-01", "2000-03-01"]))
    target = tmp_path / "budget.csv"
    export_budget_csv(budget, target, timesteps=[1], edges=edges)
    frame = pd.read_csv(target)
    assert frame["component"].tolist() == ["drain", "recharge"]
    assert set(frame["period_start"]) == {"2000-02-01 00:00:00"}
    assert set(frame["period_end"]) == {"2000-03-01 00:00:00"}
    assert "sim_id" not in frame.columns
