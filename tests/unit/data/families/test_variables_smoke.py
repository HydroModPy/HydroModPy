"""Config and custom CSV loader of the forcing and flux variables.

The nine forcing variables (etp, humidity, precipitation, radiation, recharge, runoff,
soil_moisture, temperature, wind) share one contract, played over one table. The DEM has a
different source shape and its own test. Series are daily, 2020-01-01 to 2020-03-31.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.data.variables.dem.config import IgnGeoplateformeDemSource
from hydromodpy.data.variables.forcing_series import (
    EtpConfig,
    EtpSourceConfig,
    EtpVariable,
    PrecipitationConfig,
    PrecipitationSourceConfig,
    PrecipitationVariable,
    RadiationConfig,
    RadiationSourceConfig,
    RadiationVariable,
)
from hydromodpy.data.variables.recharge.config import RechargeConfig, RechargeSourceConfig
from hydromodpy.data.variables.recharge.variable import RechargeVariable
from hydromodpy.data.variables.sim2_series import (
    HumidityConfig,
    HumiditySourceConfig,
    HumidityVariable,
    RunoffConfig,
    RunoffSourceConfig,
    RunoffVariable,
    SoilMoistureConfig,
    SoilMoistureSourceConfig,
    SoilMoistureVariable,
    TemperatureConfig,
    TemperatureSourceConfig,
    TemperatureVariable,
    WindConfig,
    WindSourceConfig,
    WindVariable,
)


def _custom_loader(variable_cls: type) -> Callable:
    """The custom loader of one variable, called like a loader function."""

    def load(cfg, *, project_period=None):
        return variable_cls(config=None, index=None, project_period=project_period).load_file(cfg)

    return load


PROJECT_PERIOD = (datetime(2020, 1, 1), datetime(2020, 3, 31))


def _make_custom_csv_dir(
    tmp_path: Path,
    variable_name: str,
    *,
    station_ids: list[str] | None = None,
    unit: str = "mm/day",
    value: float = 1.5,
) -> Path:
    """Create a minimal custom CSV directory (LOC + one chronicle per station)."""
    d = tmp_path / variable_name
    d.mkdir(parents=True, exist_ok=True)

    ids = station_ids or ["ST01"]
    pd.DataFrame(
        {
            "id": ids,
            "x": [-1.5 + i * 0.1 for i in range(len(ids))],
            "y": [48.1 + i * 0.1 for i in range(len(ids))],
            "crs": ["EPSG:4326"] * len(ids),
            "unit": [unit] * len(ids),
        }
    ).to_csv(d / f"{variable_name}_custom_LOC.csv", index=False)

    dates = pd.date_range("2020-01-01", "2020-03-31", freq="D")
    for sid in ids:
        pd.DataFrame(
            {
                "datetime": dates,
                "value": value,
            }
        ).to_csv(
            d / f"{variable_name}_custom_{sid}_20200101_20200331_D.csv",
            index=False,
        )
    return d


@dataclass(frozen=True)
class VarCase:
    """One variable's config classes, custom loader, and CSV fixture values."""

    name: str
    config_cls: type
    source_cls: type
    loader: Callable
    invalid_source: str
    unit: str
    value: float


VARIABLE_CASES = [
    VarCase("etp", EtpConfig, EtpSourceConfig, _custom_loader(EtpVariable), "noaa", "mm/day", 3.0),
    VarCase(
        "humidity",
        HumidityConfig,
        HumiditySourceConfig,
        _custom_loader(HumidityVariable),
        "era5",
        "%",
        65.0,
    ),
    VarCase(
        "precipitation",
        PrecipitationConfig,
        PrecipitationSourceConfig,
        _custom_loader(PrecipitationVariable),
        "gpm",
        "mm/day",
        5.0,
    ),
    VarCase(
        "radiation",
        RadiationConfig,
        RadiationSourceConfig,
        _custom_loader(RadiationVariable),
        "copernicus",
        "MJ/m2/j",
        12.0,
    ),
    VarCase(
        "recharge",
        RechargeConfig,
        RechargeSourceConfig,
        _custom_loader(RechargeVariable),
        "pyhelp",
        "mm/day",
        0.8,
    ),
    VarCase(
        "runoff",
        RunoffConfig,
        RunoffSourceConfig,
        _custom_loader(RunoffVariable),
        "hype",
        "mm/day",
        2.0,
    ),
    VarCase(
        "soil_moisture",
        SoilMoistureConfig,
        SoilMoistureSourceConfig,
        _custom_loader(SoilMoistureVariable),
        "smap",
        "%",
        35.0,
    ),
    VarCase(
        "temperature",
        TemperatureConfig,
        TemperatureSourceConfig,
        _custom_loader(TemperatureVariable),
        "ecmwf",
        "degC",
        15.0,
    ),
    VarCase("wind", WindConfig, WindSourceConfig, _custom_loader(WindVariable), "ncep", "m/s", 4.2),
]


CASE_IDS = [c.name for c in VARIABLE_CASES]


@pytest.mark.fast
@pytest.mark.parametrize("var_case", VARIABLE_CASES, ids=CASE_IDS)
def test_file_source_config(var_case, tmp_path):
    assert var_case.source_cls(source="file", path=tmp_path).source == "file"


@pytest.mark.fast
@pytest.mark.parametrize("var_case", VARIABLE_CASES, ids=CASE_IDS)
def test_sim2_source_config(var_case):
    assert var_case.source_cls(source="sim2").source == "sim2"


@pytest.mark.fast
@pytest.mark.parametrize("var_case", VARIABLE_CASES, ids=CASE_IDS)
def test_file_source_needs_a_path(var_case):
    with pytest.raises(ValueError, match="path"):
        var_case.source_cls(source="file")


@pytest.mark.fast
@pytest.mark.parametrize("var_case", VARIABLE_CASES, ids=CASE_IDS)
def test_custom_loader_reads_one_station(var_case, tmp_path):
    d = _make_custom_csv_dir(tmp_path, var_case.name, unit=var_case.unit, value=var_case.value)
    cfg = var_case.source_cls(source="file", path=d)

    records = var_case.loader(cfg, project_period=PROJECT_PERIOD)

    assert len(records) == 1
    assert records[0].station_id == "ST01"
    assert records[0].variable == var_case.name
    assert records[0].unit == var_case.unit
    assert records[0].has_data
    assert records[0].data["value"].iloc[0] == pytest.approx(var_case.value)


@pytest.mark.fast
def test_dem_source_of_the_ign_geoplateforme():
    cfg = IgnGeoplateformeDemSource(dataset="bd-alti", resolution_m=25.0)

    assert cfg.source == "ign_geoplateforme_dem"
    assert cfg.dataset == "bd-alti"
    assert cfg.resolution_m == pytest.approx(25.0)


@pytest.mark.fast
def test_wind_source_unit_override(tmp_path):
    cfg = WindSourceConfig(source="file", path=tmp_path, source_unit="km/h")

    assert cfg.source_unit == "km/h"
