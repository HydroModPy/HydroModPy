"""Readers of user CSV files: station chronicles (datetime, value) and station locations.

A blank or NaN value is a missing value. Every error of a file is reported at once, with its
row number counted from the first data row.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.data.ingest.tables import (
    TimeSeriesValidationError,
    infer_station_id_from_filename,
    read_locations_csv,
    read_timeseries_csv,
)

LOCATIONS_HEADER = "id,x,y,crs,unit\n"


def write_csv(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_timeseries(tmp_path):
    src = write_csv(tmp_path / "P01.csv", "datetime,value\n2020-01-01,12.5\n2020-01-02,12.6\n")

    artifact = read_timeseries_csv(src)

    assert artifact.station_id == "P01"
    assert len(artifact.records) == 2
    assert artifact.records[0][1] == pytest.approx(12.5)


def test_blank_and_nan_values_are_missing(tmp_path):
    src = write_csv(tmp_path / "P01.csv", "datetime,value\n2020-01-01,\n2020-01-02,NaN\n")

    artifact = read_timeseries_csv(src)

    assert artifact.records[0][1] is None
    assert artifact.records[1][1] is None


def test_every_error_of_a_timeseries_is_collected(tmp_path):
    src = write_csv(
        tmp_path / "P01.csv", "datetime,value\n2020-13-01,1.0\nbad,2.0\n2020-01-03,nope\n"
    )

    with pytest.raises(TimeSeriesValidationError) as info:
        read_timeseries_csv(src)

    assert len(info.value.errors) == 3


def test_locations(tmp_path):
    src = write_csv(
        tmp_path / "locs.csv",
        LOCATIONS_HEADER + "A,1.0,2.0,EPSG:4326,m\nB,3.0,4.0,EPSG:4326,m\n",
    )

    artifact = read_locations_csv(src)

    assert not artifact.errors
    assert len(artifact.stations) == 2
    assert artifact.crs == "EPSG:4326"
    assert artifact.unit == "m"


# Text of a chronicle file and the error it reports.
TIMESERIES_REFUSALS = [
    pytest.param(
        "datetime,value\n2020-13-01,1.0\n2020-01-02,2.0\n", "row 1", id="month 13 in row 1"
    ),
    pytest.param("date,val\n2020-01-01,1.0\n", "missing columns", id="wrong column names"),
]


@pytest.mark.parametrize(("text", "said"), TIMESERIES_REFUSALS)
def test_timeseries_refusals(tmp_path, text, said):
    src = write_csv(tmp_path / "P01.csv", text)

    with pytest.raises(TimeSeriesValidationError) as info:
        read_timeseries_csv(src)

    assert any(said in error for error in info.value.errors)


def test_a_station_name_with_a_space_is_refused(tmp_path):
    with pytest.raises(TimeSeriesValidationError):
        infer_station_id_from_filename(tmp_path / "bad station.csv")


# Text of a locations file and the error it reports.
LOCATIONS_REFUSALS = [
    pytest.param(
        LOCATIONS_HEADER + "A,1.0,2.0,EPSG:4326,m\nA,5.0,5.0,EPSG:4326,m\n",
        "duplicate",
        id="duplicate id",
    ),
    pytest.param("id,x,y\nA,1.0,2.0\n", "missing columns", id="no crs and unit columns"),
]


@pytest.mark.parametrize(("text", "said"), LOCATIONS_REFUSALS)
def test_locations_report_their_errors(tmp_path, text, said):
    artifact = read_locations_csv(write_csv(tmp_path / "locs.csv", text))

    assert any(said in error for error in artifact.errors)
