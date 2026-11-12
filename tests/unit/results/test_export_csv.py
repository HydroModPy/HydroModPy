"""CSV timeseries export from the run payload: identity columns, format, ordering, filters, windows."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from hydromodpy.results.exporters.csv import export_budget_csv, export_csv
from hydromodpy.results.identity import Identity

_ID = Identity(
    site="nancon",
    case_id="nancon_monthly",
    sim_id="s1",
    attempt_id="a" * 32,
    hydromodpy_version="2.0.0a5",
)
_ROW = "nancon,nancon_monthly,"
_HEADER = "site,case_id,datetime,station_id,variable,source,value,unit"


_COLUMNS = (
    "sim_id VARCHAR, station_id VARCHAR, variable VARCHAR, timestep BIGINT, "
    "time TIMESTAMPTZ, value DOUBLE, unit VARCHAR, source VARCHAR DEFAULT 'simulated'"
)


def _write_payload(path: Path, values: str) -> Path:
    """Write a ``timeseries.parquet`` payload holding *values* and return its path."""
    with duckdb.connect() as conn:
        # A session zone east of Greenwich: the file must not be shifted by it.
        conn.execute("SET TimeZone = 'Europe/Paris'")
        conn.execute(f"CREATE TABLE timeseries ({_COLUMNS})")
        conn.execute(
            "INSERT INTO timeseries (sim_id, station_id, variable, timestep, time, value, unit) "
            f"VALUES {values}"
        )
        conn.execute(
            "UPDATE timeseries SET source = 'observed', variable = replace(variable, '_obs', '') "
            "WHERE variable LIKE '%_obs'"
        )
        conn.execute(f"COPY timeseries TO '{path}' (FORMAT PARQUET)")
    return path


@pytest.fixture
def payload(tmp_path: Path) -> Path:
    return _write_payload(
        tmp_path / "timeseries.parquet",
        "('s1', 'B', 'head', 0, '2007-01-01 00:00:00+00', 2.5, 'm'), "
        "('s1', 'A', 'head', 1, '2007-01-02 00:00:00+00', 1.5, 'm'), "
        "('s1', 'A', 'head', 0, '2007-01-01 00:00:00+00', 1.0, 'm'), "
        "('s1', 'A', 'discharge', 0, NULL, 0.25, 'm3/s'), "
        "('s2', 'A', 'head', 0, '2007-01-01 00:00:00+00', 9.0, 'm')",
    )


def test_export_filters_station_and_variables(payload: Path, tmp_path: Path) -> None:
    target = tmp_path / "filtered.csv"
    export_csv(payload, "s1", target, identity=_ID, station_id="A", variables=["head"])
    lines = target.read_text().splitlines()
    assert len(lines) == 3
    assert all(",A,head," in line for line in lines[1:])


def test_export_keeps_every_variable_listed(payload: Path, tmp_path: Path) -> None:
    target = tmp_path / "both.csv"
    export_csv(payload, "s1", target, identity=_ID, station_id="A", variables=["head", "discharge"])
    assert set(pd.read_csv(target)["variable"]) == {"head", "discharge"}


def test_export_without_rows_writes_header_only(payload: Path, tmp_path: Path) -> None:
    target = tmp_path / "empty.csv"
    export_csv(payload, "missing-sim", target, identity=_ID)
    assert target.read_text().splitlines() == [_HEADER]


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
    export_budget_csv(budget, target, identity=_ID, timesteps=[1], edges=edges)
    frame = pd.read_csv(target)
    assert frame["component"].tolist() == ["drain", "recharge"]
    assert set(frame["period_start"]) == {"2000-02-01 00:00:00"}
    assert set(frame["period_end"]) == {"2000-03-01 00:00:00"}
    assert "sim_id" not in frame.columns
    assert list(frame.columns[:2]) == ["site", "case_id"]
    assert set(frame["site"]) == {"nancon"}


def test_a_run_without_series_writes_the_header_only(tmp_path: Path) -> None:
    target = tmp_path / "none.csv"
    export_csv(tmp_path / "missing.parquet", "s1", target, identity=_ID)
    assert target.read_text().splitlines() == [_HEADER]
