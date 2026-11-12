"""Intermittency stations read from a folder, and the request built for Hub'Eau.

A file folder holds a location file and one irregular chronicle per station.
The value is the ONDE flow code, where 1 is a dry stream (assec).
"""

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.data.variables.intermittency.config import IntermittencySourceConfig
from hydromodpy.data.variables.intermittency.variable import IntermittencyVariable

pytestmark = pytest.mark.fast

DATES = ["2020-05-25", "2020-06-25", "2020-07-25", "2020-08-25", "2020-09-25"]


def onde_folder(tmp_path):
    """Station A has mixed flow states (one dry date), station B always flows."""
    folder = tmp_path / "intermittency"
    folder.mkdir()
    pd.DataFrame(
        {
            "id": ["ONDE_A", "ONDE_B"],
            "x": [-1.5, -1.6],
            "y": [48.1, 48.2],
            "crs": ["EPSG:4326", "EPSG:4326"],
        }
    ).to_csv(folder / "intermittency_custom_LOC.csv", index=False)
    for station, codes in [("ONDE_A", [5, 4, 3, 1, 2]), ("ONDE_B", [5, 5, 5, 4, 5])]:
        pd.DataFrame({"datetime": DATES, "value": codes}).to_csv(
            folder / f"intermittency_custom_{station}_20200101_20201231_irregular.csv",
            index=False,
        )
    return folder


def load_file(cfg):
    return IntermittencyVariable(config=None, index=None, project_period=None).load_file(cfg)


def test_a_dry_date_is_kept(tmp_path):
    cfg = IntermittencySourceConfig(source="file", path=onde_folder(tmp_path))

    records = {record.station_id: record for record in load_file(cfg)}

    assert records["ONDE_A"].data["value"].tolist() == [5, 4, 3, 1, 2]
    assert 1 not in records["ONDE_B"].data["value"].values


def test_missing_directory_is_refused():
    cfg = IntermittencySourceConfig(source="file", path=Path("/nonexistent"))

    with pytest.raises(FileNotFoundError):
        load_file(cfg)


def test_missing_location_file_is_refused(tmp_path):
    cfg = IntermittencySourceConfig(source="file", path=tmp_path)

    with pytest.raises(FileNotFoundError, match="intermittency_custom_LOC"):
        load_file(cfg)


def test_a_department_code_alone_gives_the_department_extent(tmp_path):
    cfg = IntermittencySourceConfig(source="hubeau", code_departement=["35"])
    variable = IntermittencyVariable(config=None, index=None, project_extent=None)

    request = variable._station_request(
        cfg,
        out_dir=tmp_path,
        station_ids=(),
        bbox=None,
        start=datetime(2020, 1, 1),
        end=datetime(2020, 1, 31),
    )

    assert request.station_ids == ()
    assert request.extent.crs == "EPSG:4326"
    # Ille-et-Vilaine, in degrees.
    assert -2.5 < request.extent.xmin < -1.5
    assert 47.5 < request.extent.ymin < 48.5
