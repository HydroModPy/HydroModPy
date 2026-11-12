"""Hydrometry station files read from a folder.

The folder holds one location file (id, x, y, crs and optionally unit) and one
daily chronicle per station. A discharge in L/s is stored in m3/s.
"""

from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.core.exceptions import DataSourceError
from hydromodpy.data.variables.hydrometry.config import HydrometrySourceConfig
from hydromodpy.data.variables.hydrometry.variable import HydrometryVariable

STATIONS = ("ST001", "ST002")


def station_folder(tmp_path, *, loc_unit="m3/s", stations=STATIONS, value=2500.0):
    """Folder of daily chronicles, all at the same value, with an optional unit in the LOC file."""
    folder = tmp_path / "hydro"
    folder.mkdir()
    loc = {
        "id": list(stations),
        "x": [-1.5 - 0.1 * i for i in range(len(stations))],
        "y": [48.1 + 0.1 * i for i in range(len(stations))],
        "crs": ["EPSG:4326"] * len(stations),
    }
    if loc_unit is not None:
        loc["unit"] = [loc_unit] * len(stations)
    pd.DataFrame(loc).to_csv(folder / "hydrometry_custom_LOC.csv", index=False)
    dates = pd.date_range("2020-01-01", "2020-03-31", freq="D")
    for station in stations:
        pd.DataFrame({"datetime": dates, "value": value}).to_csv(
            folder / f"hydrometry_custom_{station}_20200101_20200331_D.csv", index=False
        )
    return folder


def load_file(cfg, project_period=None):
    return HydrometryVariable(config=None, index=None, project_period=project_period).load_file(cfg)


def test_station_ids_filter_the_records(tmp_path, project_period):
    cfg = HydrometrySourceConfig(
        source="file", path=station_folder(tmp_path), station_ids=["ST001"]
    )

    records = load_file(cfg, project_period)

    assert [record.station_id for record in records] == ["ST001"]


UNITS = [
    pytest.param("L/s", None, "L/s", id="L/s in the LOC file"),
    pytest.param("l/s", None, "l/s", id="lowercase l/s in the LOC file"),
    pytest.param(None, "L/s", "L/s", id="unit given by the config"),
]


@pytest.mark.parametrize(("loc_unit", "config_unit", "source_unit"), UNITS)
def test_discharge_is_stored_in_m3_s(tmp_path, project_period, loc_unit, config_unit, source_unit):
    folder = station_folder(tmp_path, loc_unit=loc_unit, stations=("ST01",))
    cfg = HydrometrySourceConfig(source="file", path=folder, source_unit=config_unit)

    records = load_file(cfg, project_period)

    # 2500 L/s -> 2.5 m3/s
    assert records[0].data["value"].iloc[0] == pytest.approx(2.5)
    assert records[0].unit == "m3/s"
    assert records[0].source_unit == source_unit


def test_refusal_names_the_ids_the_file_holds(tmp_path, project_period):
    cfg = HydrometrySourceConfig(
        source="file", path=station_folder(tmp_path), station_ids=["ST001", "NANCON"]
    )

    with pytest.raises(DataSourceError) as excinfo:
        load_file(cfg, project_period)

    assert "NANCON" in str(excinfo.value)
    assert "ST001" in str(excinfo.value)


REFUSALS = [
    # A calibration scored against an empty observed series still reports a number.
    pytest.param(
        "m3/s", ["ST999"], None, DataSourceError, "ST999", id="station id not in the file"
    ),
    pytest.param(None, None, None, ValueError, "No unit", id="no unit anywhere"),
    pytest.param("m3/s", None, "L/s", ValueError, "source_unit", id="config unit contradicts LOC"),
]


@pytest.mark.parametrize(("loc_unit", "station_ids", "config_unit", "error", "match"), REFUSALS)
def test_refusals(tmp_path, project_period, loc_unit, station_ids, config_unit, error, match):
    cfg = HydrometrySourceConfig(
        source="file",
        path=station_folder(tmp_path, loc_unit=loc_unit),
        station_ids=station_ids,
        source_unit=config_unit,
    )

    with pytest.raises(error, match=match):
        load_file(cfg, project_period)


def test_missing_directory_is_refused(project_period):
    cfg = HydrometrySourceConfig(source="file", path=Path("/nonexistent"))

    with pytest.raises(FileNotFoundError):
        load_file(cfg, project_period)
