"""Tests for the CSV -> Parquet drag-and-drop adapter."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.data.adapters.csv_to_parquet import (
    TimeSeriesValidationError,
    convert_timeseries_csv_to_parquet,
    infer_station_id_from_filename,
    iter_chronicle_files,
    read_locations_csv,
    read_timeseries_csv,
)


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_read_timeseries_csv_basic(tmp_path):
    src = _write(
        tmp_path / "P01.csv",
        "datetime,value\n2020-01-01,12.5\n2020-01-02,12.6\n",
    )
    artifact = read_timeseries_csv(src)
    assert artifact.station_id == "P01"
    assert len(artifact.records) == 2
    assert artifact.records[0][1] == pytest.approx(12.5)


def test_read_timeseries_csv_allows_blank_value(tmp_path):
    src = _write(
        tmp_path / "P01.csv",
        "datetime,value\n2020-01-01,\n2020-01-02,NaN\n",
    )
    artifact = read_timeseries_csv(src)
    assert artifact.records[0][1] is None
    assert artifact.records[1][1] is None


def test_read_timeseries_csv_rejects_bad_datetime(tmp_path):
    src = _write(
        tmp_path / "P01.csv",
        "datetime,value\n2020-13-01,1.0\n2020-01-02,2.0\n",
    )
    with pytest.raises(TimeSeriesValidationError) as exc_info:
        read_timeseries_csv(src)
    assert any("row 1" in e for e in exc_info.value.errors)


def test_read_timeseries_csv_collects_all_errors(tmp_path):
    src = _write(
        tmp_path / "P01.csv",
        "datetime,value\n2020-13-01,1.0\nbad,2.0\n2020-01-03,nope\n",
    )
    with pytest.raises(TimeSeriesValidationError) as exc_info:
        read_timeseries_csv(src)
    assert len(exc_info.value.errors) == 3


def test_read_timeseries_csv_rejects_missing_columns(tmp_path):
    src = _write(tmp_path / "P01.csv", "date,val\n2020-01-01,1.0\n")
    with pytest.raises(TimeSeriesValidationError):
        read_timeseries_csv(src)


def test_infer_station_id_from_filename_rejects_invalid(tmp_path):
    with pytest.raises(TimeSeriesValidationError):
        infer_station_id_from_filename(tmp_path / "bad station.csv")


def test_convert_timeseries_csv_to_parquet_writes_file(tmp_path):
    src = _write(
        tmp_path / "P01.csv",
        "datetime,value\n2020-01-01,1.5\n2020-01-02,2.5\n",
    )
    dest = tmp_path / "out" / "P01.parquet"
    written = convert_timeseries_csv_to_parquet(src, dest)
    assert written == dest
    assert dest.exists()
    assert dest.stat().st_size > 0


def test_read_locations_csv_ok(tmp_path):
    src = _write(
        tmp_path / "locs.csv",
        "id,x,y,crs,unit\nA,1.0,2.0,EPSG:4326,m\nB,3.0,4.0,EPSG:4326,m\n",
    )
    artifact = read_locations_csv(src)
    assert not artifact.errors
    assert len(artifact.stations) == 2
    assert artifact.crs == "EPSG:4326"
    assert artifact.unit == "m"


def test_read_locations_csv_reports_duplicates(tmp_path):
    src = _write(
        tmp_path / "locs.csv",
        "id,x,y,crs,unit\nA,1.0,2.0,EPSG:4326,m\nA,5.0,5.0,EPSG:4326,m\n",
    )
    artifact = read_locations_csv(src)
    assert any("duplicate" in e for e in artifact.errors)


def test_read_locations_csv_reports_missing_columns(tmp_path):
    src = _write(tmp_path / "locs.csv", "id,x,y\nA,1.0,2.0\n")
    artifact = read_locations_csv(src)
    assert any("missing columns" in e for e in artifact.errors)


def test_iter_chronicle_files_skips_example(tmp_path):
    chronicles = tmp_path / "chronicles"
    chronicles.mkdir()
    _write(chronicles / "EXAMPLE.csv", "datetime,value\n")
    _write(chronicles / "P01.csv", "datetime,value\n2020-01-01,1.0\n")
    _write(chronicles / "_hidden.csv", "datetime,value\n")
    _write(chronicles / "README.md", "ignored")

    files = list(iter_chronicle_files(tmp_path))
    assert [p.name for p in files] == ["P01.csv"]


def test_comments_and_blank_lines_are_ignored(tmp_path):
    src = _write(
        tmp_path / "P01.csv",
        "# a comment\ndatetime,value\n2020-01-01,1.0\n",
    )
    artifact = read_timeseries_csv(src)
    assert len(artifact.records) == 1
