"""CSV export of station records: a metadata table, a table of contents and one chronicle per station."""

from datetime import datetime

import pandas as pd

from hydromodpy.data.common.export import export_records
from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.variables.hydrometry.config import HydrometryConfig, HydrometrySourceConfig
from hydromodpy.data.variables.hydrometry.variable import HydrometryVariable


def daily_record(station_id, n_days, location=None):
    dates = pd.date_range("2020-01-01", periods=n_days, freq="D")
    return PointRecord(
        station_id=station_id,
        variable="discharge",
        source="file",
        unit="m3/s",
        frequency="D",
        data=pd.DataFrame({"datetime": dates, "value": range(n_days)}),
        date_start=datetime(2020, 1, 1),
        date_end=datetime(2020, 1, n_days),
        location=location,
        source_unit="L/s" if location else None,
    )


def test_export_records(tmp_path):
    records = [
        daily_record("S1", 10, StationLocation(id="S1", x=-1.5, y=48.0, crs="EPSG:4326")),
        daily_record("S2", 5, StationLocation(id="S2", x=-1.6, y=48.1, crs="EPSG:4326")),
    ]

    result = export_records(records, tmp_path / "out", prefix="hydro")

    assert {"metadata", "table_of_contents", "chronicle_S1", "chronicle_S2"} <= set(result)
    meta = pd.read_csv(result["metadata"])
    assert len(meta) == 2
    assert {"station_id", "source_unit", "x", "y"} <= set(meta.columns)
    assert meta.loc[0, "source_unit"] == "L/s"
    toc = pd.read_csv(result["table_of_contents"])
    assert len(toc) == 2
    assert {"file", "n_records", "source_unit"} <= set(toc.columns)
    chronicle = pd.read_csv(result["chronicle_S1"])
    assert len(chronicle) == 10
    assert list(chronicle.columns) == ["datetime", "value"]


def test_no_record_exports_nothing(tmp_path):
    assert export_records([], tmp_path / "empty") == {}


def test_a_record_without_location_still_exports(tmp_path):
    result = export_records([daily_record("X", 5)], tmp_path / "noloc", prefix="test")

    meta = pd.read_csv(result["metadata"])
    assert len(meta) == 1
    assert "x" not in meta.columns


def test_a_variable_exports_its_records(sample_hydro_dir, project_period, tmp_path):
    config = HydrometryConfig(
        sources=[HydrometrySourceConfig(source="file", path=sample_hydro_dir)]
    )
    variable = HydrometryVariable(config=config, index=None, project_period=project_period)

    result = variable.export(variable.load(), tmp_path / "export")

    assert "metadata" in result
    assert "table_of_contents" in result
    assert (tmp_path / "export" / "hydrometry_metadata.csv").exists()
    assert (tmp_path / "export" / "hydrometry_table_of_contents.csv").exists()
