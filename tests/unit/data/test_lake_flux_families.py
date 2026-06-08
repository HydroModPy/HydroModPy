"""Lake volumetric flux families register, scaffold-scan, and load.

Guards the three per-lake volumetric (L^3/T) timeseries families
(``lake_inflow``, ``lake_outflow``, ``lake_withdrawal``) modelled on the
``lake_levels`` family: each is dispatchable, listed as a scaffold variable
and a supported data-manager type, and its manager loads a custom CSV
directory into PointRecord timeseries.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from hydromodpy.data._dispatch import VARIABLE_SPECS, get_manager_class
from hydromodpy.data.base_manager_variable import BaseVariableManager
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.data_managers_config import SUPPORTED_DATA_MANAGER_TYPES
from hydromodpy.data.scaffold import VARIABLES
from hydromodpy.data.variables.lake_inflow.config import LakeInflowConfig
from hydromodpy.data.variables.lake_inflow.manager import LakeInflowManager
from hydromodpy.data.variables.lake_outflow.config import LakeOutflowConfig
from hydromodpy.data.variables.lake_outflow.manager import LakeOutflowManager
from hydromodpy.data.variables.lake_withdrawal.config import LakeWithdrawalConfig
from hydromodpy.data.variables.lake_withdrawal.manager import LakeWithdrawalManager

PROJECT_PERIOD = (datetime(2020, 1, 1), datetime(2020, 3, 31))

FLUX_FAMILIES = ("lake_inflow", "lake_outflow", "lake_withdrawal")

MANAGER_CLASSES = {
    "lake_inflow": (LakeInflowConfig, LakeInflowManager),
    "lake_outflow": (LakeOutflowConfig, LakeOutflowManager),
    "lake_withdrawal": (LakeWithdrawalConfig, LakeWithdrawalManager),
}


def _make_lake_flux_dir(tmp_path, variable_name, *, lake_ids, unit="m3/s", value=3.0):
    """Create a custom CSV directory (LOC + one chronicle per lake id)."""
    d = tmp_path / variable_name
    d.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(
        {
            "id": lake_ids,
            "x": [-1.5 + i * 0.1 for i in range(len(lake_ids))],
            "y": [48.1 + i * 0.1 for i in range(len(lake_ids))],
            "crs": ["EPSG:4326"] * len(lake_ids),
            "unit": [unit] * len(lake_ids),
        }
    ).to_csv(d / f"{variable_name}_custom_LOC.csv", index=False)

    dates = pd.date_range("2020-01-01", "2020-03-31", freq="D")
    for lake_id in lake_ids:
        pd.DataFrame({"datetime": dates, "value": value}).to_csv(
            d / f"{variable_name}_custom_{lake_id}_20200101_20200331_D.csv",
            index=False,
        )
    return d


@pytest.mark.parametrize("name", FLUX_FAMILIES)
def test_family_registers_in_dispatch(name):
    spec = VARIABLE_SPECS[name]
    assert spec.config_module == f"hydromodpy.data.variables.{name}.config"
    assert spec.manager_module == f"hydromodpy.data.variables.{name}.manager"

    manager_cls = get_manager_class(name)
    assert issubclass(manager_cls, BaseVariableManager)
    assert manager_cls.VARIABLE_NAME == name
    assert manager_cls.INTERNAL_UNIT == "m3/s"


@pytest.mark.parametrize("name", FLUX_FAMILIES)
def test_family_is_supported_data_manager_type(name):
    assert name in SUPPORTED_DATA_MANAGER_TYPES


@pytest.mark.parametrize("name", FLUX_FAMILIES)
def test_family_scaffold_scans_as_point_timeseries(name):
    spec = next(s for s in VARIABLES if s.name == name)
    assert spec.category == "point"
    assert spec.kind == "timeseries"
    assert spec.unit == "m3/s"


def test_manager_load_returns_point_timeseries_contract(tmp_path):
    config_cls, manager_cls = MANAGER_CLASSES["lake_inflow"]
    data_dir = _make_lake_flux_dir(
        tmp_path,
        "lake_inflow",
        lake_ids=["LAC01", "LAC02"],
    )
    config = config_cls.from_csv_directory(data_dir)
    manager = manager_cls(
        config=config,
        catalog=None,
        project_period=PROJECT_PERIOD,
        data_dir=data_dir,
    )

    result = manager.load()

    assert len(result.points) == 2
    for record in result.points:
        assert isinstance(record, PointRecord)
        assert record.variable == "lake_inflow"
        assert record.source == "custom"
        assert record.unit == "m3/s"
        assert record.has_data
        assert list(record.data.columns[:2]) == ["datetime", "value"]
        assert record.data["value"].iloc[0] == pytest.approx(3.0)

    assert {r.station_id for r in result.points} == {"LAC01", "LAC02"}
