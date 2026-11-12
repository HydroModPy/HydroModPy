"""Per-lake time series read from a folder of CSV files.

The three flux families (inflow, outflow, withdrawal, in m3/s) and the lake
levels (m) are data variables, listed by the scaffold as point time series, and
their classes load a LOC file plus one chronicle per lake into point records.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.loading._dispatch import VARIABLE_SPECS
from hydromodpy.data.loading.config_schema import DATA_VARIABLES
from hydromodpy.data.provenance.sidecars import CacheIndex, sidecar_path_for
from hydromodpy.data.variables.lake_series import (
    LakeInflowConfig,
    LakeInflowVariable,
    LakeLevelsConfig,
    LakeLevelsVariable,
    LakeOutflowConfig,
    LakeOutflowVariable,
    LakeWithdrawalConfig,
    LakeWithdrawalVariable,
)

PROJECT_PERIOD = (datetime(2020, 1, 1), datetime(2020, 3, 31))

FLUX_FAMILIES = ("lake_inflow", "lake_outflow", "lake_withdrawal")

VARIABLE_CLASSES = {
    "lake_inflow": (LakeInflowConfig, LakeInflowVariable),
    "lake_outflow": (LakeOutflowConfig, LakeOutflowVariable),
    "lake_withdrawal": (LakeWithdrawalConfig, LakeWithdrawalVariable),
}


def lake_folder(tmp_path, variable_name, *, lake_ids, unit="m3/s", values=(3.0,)):
    """Custom CSV folder with a LOC file and one daily chronicle per lake id."""
    folder = tmp_path / variable_name
    folder.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "id": lake_ids,
            "x": [-1.5 + i * 0.1 for i in range(len(lake_ids))],
            "y": [48.1 + i * 0.1 for i in range(len(lake_ids))],
            "crs": ["EPSG:4326"] * len(lake_ids),
            "unit": [unit] * len(lake_ids),
        }
    ).to_csv(folder / f"{variable_name}_custom_LOC.csv", index=False)
    dates = pd.date_range("2020-01-01", periods=len(values), freq="D")
    for lake_id in lake_ids:
        pd.DataFrame({"datetime": dates, "value": values}).to_csv(
            folder / f"{variable_name}_custom_{lake_id}_{dates[0]:%Y%m%d}_{dates[-1]:%Y%m%d}_D.csv",
            index=False,
        )
    return folder


@pytest.mark.parametrize("name", FLUX_FAMILIES)
def test_flux_family_is_registered(name):
    assert name in DATA_VARIABLES
    spec = VARIABLE_SPECS[name]
    assert (spec.category, spec.kind, spec.unit) == ("point", "timeseries", "m3/s")


@pytest.mark.parametrize("name", FLUX_FAMILIES)
def test_flux_family_loads_point_records(tmp_path, name):
    config_cls, variable_cls = VARIABLE_CLASSES[name]
    folder = lake_folder(tmp_path, name, lake_ids=["LAC01", "LAC02"], values=[3.0] * 91)
    variable = variable_cls(
        config=config_cls.from_csv_directory(folder),
        index=None,
        project_period=PROJECT_PERIOD,
        data_dir=folder,
    )

    result = variable.load()

    assert {record.station_id for record in result.points} == {"LAC01", "LAC02"}
    for record in result.points:
        assert isinstance(record, PointRecord)
        assert record.variable == name
        assert record.source == "file"
        assert record.unit == "m3/s"
        assert record.has_data
        assert list(record.data.columns[:2]) == ["datetime", "value"]
        assert record.data["value"].iloc[0] == pytest.approx(3.0)


def test_levels_load_as_point_records_without_a_cache_row(tmp_path):
    folder = lake_folder(
        tmp_path, "lake_levels", lake_ids=["lac0"], unit="m", values=[85.0, 85.5, 86.0]
    )
    index = CacheIndex(tmp_path)
    variable = LakeLevelsVariable(
        config=LakeLevelsConfig.from_csv_directory(folder), index=index, data_dir=folder
    )

    result = variable.load()

    assert result.has_points
    assert not result.has_fields
    assert not result.has_tables
    (record,) = result.points
    assert isinstance(record, PointRecord)
    assert record.variable == "lake_level"
    assert record.source == "file"
    assert record.station_id == "lac0"
    assert record.unit == "m"
    assert record.data["value"].tolist() == [85.0, 85.5, 86.0]
    # A user file is no row of the data cache, and nothing writes a sidecar beside it.
    assert index.rows() == []
    assert not any(sidecar_path_for(path).exists() for path in folder.glob("*.csv"))
