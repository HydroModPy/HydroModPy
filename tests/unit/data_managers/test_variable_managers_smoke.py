"""Smoke tests for the 10 variable managers that lack dedicated tests.

Covers config validation (valid + invalid) and the custom CSV loader for:
dem, etp, humidity, precipitation, radiation, recharge, runoff,
soil_moisture, temperature, wind.

The nine forcing/flux variables share an identical config + custom-loader
contract, so they are driven from one parametrized table (``VARIABLE_CASES``).
DEM has a different source shape and keeps its own class. Variable-specific
behaviour (ETP date window, precipitation/radiation components, recharge
synthetic source, ...) lives in the per-variable ``*Specific`` classes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

# ── Config imports ────────────────────────────────────────────────────
from hydromodpy.data.variables.dem.config import (
    CustomDemSource,
    DemConfig,
    IgnGeoplateformeDemSource,
)
from hydromodpy.data.variables.etp.config import EtpConfig, EtpSourceConfig
from hydromodpy.data.variables.etp.custom import load_custom as load_etp
from hydromodpy.data.variables.humidity.config import HumidityConfig, HumiditySourceConfig
from hydromodpy.data.variables.humidity.custom import load_custom as load_humidity
from hydromodpy.data.variables.precipitation.config import (
    PrecipitationConfig,
    PrecipitationSourceConfig,
)
from hydromodpy.data.variables.precipitation.custom import load_custom as load_precipitation
from hydromodpy.data.variables.radiation.config import RadiationConfig, RadiationSourceConfig
from hydromodpy.data.variables.radiation.custom import load_custom as load_radiation
from hydromodpy.data.variables.recharge.config import RechargeConfig, RechargeSourceConfig
from hydromodpy.data.variables.recharge.custom import load_custom as load_recharge
from hydromodpy.data.variables.runoff.config import RunoffConfig, RunoffSourceConfig
from hydromodpy.data.variables.runoff.custom import load_custom as load_runoff
from hydromodpy.data.variables.soil_moisture.config import (
    SoilMoistureConfig,
    SoilMoistureSourceConfig,
)
from hydromodpy.data.variables.soil_moisture.custom import load_custom as load_soil_moisture
from hydromodpy.data.variables.temperature.config import TemperatureConfig, TemperatureSourceConfig
from hydromodpy.data.variables.temperature.custom import load_custom as load_temperature
from hydromodpy.data.variables.wind.config import WindConfig, WindSourceConfig
from hydromodpy.data.variables.wind.custom import load_custom as load_wind

# ── Shared helpers ────────────────────────────────────────────────────

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


# =====================================================================
# Parametrized contract shared by the nine forcing/flux variables
# =====================================================================


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
    VarCase("etp", EtpConfig, EtpSourceConfig, load_etp, "noaa", "mm/day", 3.0),
    VarCase("humidity", HumidityConfig, HumiditySourceConfig, load_humidity, "era5", "%", 65.0),
    VarCase(
        "precipitation",
        PrecipitationConfig,
        PrecipitationSourceConfig,
        load_precipitation,
        "gpm",
        "mm/day",
        5.0,
    ),
    VarCase(
        "radiation",
        RadiationConfig,
        RadiationSourceConfig,
        load_radiation,
        "copernicus",
        "MJ/m2/j",
        12.0,
    ),
    VarCase(
        "recharge", RechargeConfig, RechargeSourceConfig, load_recharge, "pyhelp", "mm/day", 0.8
    ),
    VarCase("runoff", RunoffConfig, RunoffSourceConfig, load_runoff, "hype", "mm/day", 2.0),
    VarCase(
        "soil_moisture",
        SoilMoistureConfig,
        SoilMoistureSourceConfig,
        load_soil_moisture,
        "smap",
        "%",
        35.0,
    ),
    VarCase(
        "temperature",
        TemperatureConfig,
        TemperatureSourceConfig,
        load_temperature,
        "ecmwf",
        "degC",
        15.0,
    ),
    VarCase("wind", WindConfig, WindSourceConfig, load_wind, "ncep", "m/s", 4.2),
]


@pytest.fixture(params=VARIABLE_CASES, ids=[c.name for c in VARIABLE_CASES])
def var_case(request) -> VarCase:
    return request.param


@pytest.mark.fast
class TestVariableConfigContract:
    def test_valid_custom_source(self, var_case, tmp_path):
        cfg = var_case.source_cls(source="custom", path=tmp_path)
        assert cfg.source == "custom"

    def test_valid_sim2_source(self, var_case):
        cfg = var_case.source_cls(source="sim2")
        assert cfg.source == "sim2"

    def test_custom_requires_path(self, var_case):
        with pytest.raises(ValueError, match="path"):
            var_case.source_cls(source="custom")

    def test_invalid_source_rejected(self, var_case):
        with pytest.raises(ValueError):
            var_case.source_cls(source=var_case.invalid_source)

    def test_top_level_config(self, var_case, tmp_path):
        cfg = var_case.config_cls(sources=[var_case.source_cls(source="custom", path=tmp_path)])
        assert len(cfg.sources) == 1

    def test_empty_sources_rejected(self, var_case):
        with pytest.raises(ValueError):
            var_case.config_cls(sources=[])


@pytest.mark.fast
class TestVariableCustomLoaderContract:
    def test_load_one_station(self, var_case, tmp_path):
        d = _make_custom_csv_dir(tmp_path, var_case.name, unit=var_case.unit, value=var_case.value)
        cfg = var_case.source_cls(source="custom", path=d)
        records = var_case.loader(cfg, project_period=PROJECT_PERIOD)
        assert len(records) == 1
        assert records[0].station_id == "ST01"
        assert records[0].variable == var_case.name
        assert records[0].unit == var_case.unit
        assert records[0].has_data
        assert records[0].data["value"].iloc[0] == pytest.approx(var_case.value)

    def test_missing_loc_file_raises(self, var_case, tmp_path):
        d = tmp_path / f"{var_case.name}_empty"
        d.mkdir()
        cfg = var_case.source_cls(source="custom", path=d)
        with pytest.raises(FileNotFoundError, match=f"{var_case.name}_custom_LOC"):
            var_case.loader(cfg, project_period=PROJECT_PERIOD)


# =====================================================================
# DEM (distinct source shape, no custom loader)
# =====================================================================


@pytest.mark.fast
class TestDemConfig:
    def test_valid_custom_source(self, tmp_path):
        cfg = CustomDemSource(path=tmp_path)
        assert cfg.source == "custom"
        assert cfg.path == tmp_path

    def test_valid_ign_geoplateforme_source(self):
        cfg = IgnGeoplateformeDemSource(dataset="bd-alti", resolution_m=25.0)
        assert cfg.source == "ign_geoplateforme_dem"
        assert cfg.dataset == "bd-alti"
        assert cfg.resolution_m == pytest.approx(25.0)

    def test_custom_requires_path(self):
        with pytest.raises(ValueError, match="path"):
            CustomDemSource()

    def test_invalid_source_rejected(self):
        with pytest.raises(ValueError):
            DemConfig(sources=[{"source": "invalid_source"}])

    def test_ign_bdalti_source_rejected(self):
        with pytest.raises(ValueError):
            DemConfig(sources=[{"source": "ign_bdalti", "resolution_m": 25.0}])

    def test_rge_alti_dataset_rejected_for_assembled_geoplateforme_source(self):
        with pytest.raises(ValueError):
            IgnGeoplateformeDemSource(dataset="rge-alti")

    def test_top_level_config(self, tmp_path):
        cfg = DemConfig(sources=[CustomDemSource(path=tmp_path)])
        assert len(cfg.sources) == 1

    def test_empty_sources_rejected(self):
        with pytest.raises(ValueError):
            DemConfig(sources=[])

    def test_extra_fields_forbidden(self, tmp_path):
        with pytest.raises(ValueError):
            CustomDemSource(path=tmp_path, bogus=True)


# =====================================================================
# Variable-specific behaviour
# =====================================================================


@pytest.mark.fast
class TestEtpSpecific:
    def test_custom_source_defaults_col_id(self, tmp_path):
        cfg = EtpSourceConfig(source="custom", path=tmp_path)
        assert cfg.col_id == "id"

    def test_top_level_with_dates(self, tmp_path):
        cfg = EtpConfig(
            sources=[EtpSourceConfig(source="custom", path=tmp_path)],
            date_start="2020-01-01",
            date_end="2020-12-31",
        )
        assert cfg.date_start == "2020-01-01"

    def test_bad_date_format_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="Invalid ISO date"):
            EtpConfig(
                sources=[EtpSourceConfig(source="custom", path=tmp_path)],
                date_start="01-01-2020",
            )

    def test_date_order_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="date_start must be before date_end"):
            EtpConfig(
                sources=[EtpSourceConfig(source="custom", path=tmp_path)],
                date_start="2021-01-01",
                date_end="2020-01-01",
            )


@pytest.mark.fast
class TestPrecipitationSpecific:
    def test_custom_source_defaults_components_total(self, tmp_path):
        cfg = PrecipitationSourceConfig(source="custom", path=tmp_path)
        assert cfg.components == ["total"]

    def test_components_liquid_solid(self, tmp_path):
        cfg = PrecipitationSourceConfig(
            source="custom",
            path=tmp_path,
            components=["liquid", "solid"],
        )
        assert cfg.components == ["liquid", "solid"]

    def test_invalid_component_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            PrecipitationSourceConfig(source="custom", path=tmp_path, components=["hail"])

    def test_empty_components_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            PrecipitationSourceConfig(source="custom", path=tmp_path, components=[])


@pytest.mark.fast
class TestRadiationSpecific:
    def test_custom_source_defaults_components(self, tmp_path):
        cfg = RadiationSourceConfig(source="custom", path=tmp_path)
        assert cfg.components == ["atmospheric", "visible"]

    def test_components_atmospheric_only(self, tmp_path):
        cfg = RadiationSourceConfig(source="custom", path=tmp_path, components=["atmospheric"])
        assert cfg.components == ["atmospheric"]

    def test_invalid_component_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            RadiationSourceConfig(source="custom", path=tmp_path, components=["infrared"])


@pytest.mark.fast
class TestRechargeSpecific:
    def test_valid_synthetic_source(self):
        cfg = RechargeSourceConfig(source="synthetic", values=[0.5])
        assert cfg.source == "synthetic"
        assert cfg.values == [0.5]

    def test_synthetic_requires_values(self):
        with pytest.raises(ValueError, match="values"):
            RechargeSourceConfig(source="synthetic")

    def test_synthetic_with_amplitude(self):
        cfg = RechargeSourceConfig(
            source="synthetic",
            values=[1.0],
            amplitude=0.5,
            period_days=365,
        )
        assert cfg.amplitude == 0.5
        assert cfg.period_days == 365


@pytest.mark.fast
class TestRunoffSpecific:
    def test_two_stations(self, tmp_path):
        d = _make_custom_csv_dir(
            tmp_path,
            "runoff",
            station_ids=["R01", "R02"],
            unit="mm/day",
            value=1.0,
        )
        cfg = RunoffSourceConfig(source="custom", path=d)
        records = load_runoff(cfg, project_period=PROJECT_PERIOD)
        assert len(records) == 2
        assert {r.station_id for r in records} == {"R01", "R02"}


@pytest.mark.fast
class TestTemperatureSpecific:
    def test_station_ids_filtering(self, tmp_path):
        cfg = TemperatureSourceConfig(source="custom", path=tmp_path, station_ids=["T01", "T02"])
        assert cfg.station_ids == ["T01", "T02"]


@pytest.mark.fast
class TestWindSpecific:
    def test_source_unit_override(self, tmp_path):
        cfg = WindSourceConfig(source="custom", path=tmp_path, source_unit="km/h")
        assert cfg.source_unit == "km/h"
