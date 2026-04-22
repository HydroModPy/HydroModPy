"""Smoke tests for the 10 variable managers that lack dedicated tests.

Covers config validation (valid + invalid) and custom CSV loader for:
dem, etp, humidity, precipitation, radiation, recharge, runoff,
soil_moisture, temperature, wind.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

# ── Config imports ────────────────────────────────────────────────────
from hydromodpy.data.variables.dem.config import DemConfig, DemSourceConfig
from hydromodpy.data.variables.etp.config import EtpConfig, EtpSourceConfig
from hydromodpy.data.variables.humidity.config import HumidityConfig, HumiditySourceConfig
from hydromodpy.data.variables.precipitation.config import (
    PrecipitationConfig,
    PrecipitationSourceConfig,
)
from hydromodpy.data.variables.radiation.config import RadiationConfig, RadiationSourceConfig
from hydromodpy.data.variables.recharge.config import RechargeConfig, RechargeSourceConfig
from hydromodpy.data.variables.runoff.config import RunoffConfig, RunoffSourceConfig
from hydromodpy.data.variables.soil_moisture.config import (
    SoilMoistureConfig,
    SoilMoistureSourceConfig,
)
from hydromodpy.data.variables.temperature.config import TemperatureConfig, TemperatureSourceConfig
from hydromodpy.data.variables.wind.config import WindConfig, WindSourceConfig

# ── Custom loader imports ─────────────────────────────────────────────
from hydromodpy.data.variables.etp.custom import load_custom as load_etp
from hydromodpy.data.variables.humidity.custom import load_custom as load_humidity
from hydromodpy.data.variables.precipitation.custom import load_custom as load_precipitation
from hydromodpy.data.variables.radiation.custom import load_custom as load_radiation
from hydromodpy.data.variables.recharge.custom import load_custom as load_recharge
from hydromodpy.data.variables.runoff.custom import load_custom as load_runoff
from hydromodpy.data.variables.soil_moisture.custom import load_custom as load_soil_moisture
from hydromodpy.data.variables.temperature.custom import load_custom as load_temperature
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
# DEM
# =====================================================================


@pytest.mark.fast
class TestDemConfig:
    def test_valid_custom_source(self, tmp_path):
        cfg = DemSourceConfig(source="custom", path=tmp_path)
        assert cfg.source == "custom"
        assert cfg.path == tmp_path

    def test_valid_ign_source(self):
        cfg = DemSourceConfig(source="ign_bdalti")
        assert cfg.source == "ign_bdalti"

    def test_custom_requires_path(self):
        with pytest.raises(ValueError, match="path"):
            DemSourceConfig(source="custom")

    def test_invalid_source_rejected(self):
        with pytest.raises(ValueError):
            DemSourceConfig(source="invalid_source")

    def test_top_level_config(self, tmp_path):
        cfg = DemConfig(sources=[DemSourceConfig(source="custom", path=tmp_path)])
        assert len(cfg.sources) == 1

    def test_empty_sources_rejected(self):
        with pytest.raises(ValueError):
            DemConfig(sources=[])

    def test_extra_fields_forbidden(self, tmp_path):
        with pytest.raises(ValueError):
            DemSourceConfig(source="custom", path=tmp_path, bogus=True)


# =====================================================================
# ETP
# =====================================================================


@pytest.mark.fast
class TestEtpConfig:
    def test_valid_custom_source(self, tmp_path):
        cfg = EtpSourceConfig(source="custom", path=tmp_path)
        assert cfg.source == "custom"
        assert cfg.col_id == "id"

    def test_valid_sim2_source(self):
        cfg = EtpSourceConfig(source="sim2")
        assert cfg.source == "sim2"

    def test_custom_requires_path(self):
        with pytest.raises(ValueError, match="path"):
            EtpSourceConfig(source="custom")

    def test_invalid_source_rejected(self):
        with pytest.raises(ValueError):
            EtpSourceConfig(source="noaa")

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

    def test_empty_sources_rejected(self):
        with pytest.raises(ValueError):
            EtpConfig(sources=[])


@pytest.mark.fast
class TestEtpCustomLoader:
    def test_load_one_station(self, tmp_path):
        d = _make_custom_csv_dir(tmp_path, "etp", unit="mm/day", value=3.0)
        cfg = EtpSourceConfig(source="custom", path=d)
        records = load_etp(cfg, project_period=PROJECT_PERIOD)
        assert len(records) == 1
        assert records[0].station_id == "ST01"
        assert records[0].variable == "etp"
        assert records[0].unit == "mm/day"
        assert records[0].has_data

    def test_missing_loc_file_raises(self, tmp_path):
        d = tmp_path / "etp_empty"
        d.mkdir()
        cfg = EtpSourceConfig(source="custom", path=d)
        with pytest.raises(FileNotFoundError, match="etp_custom_LOC"):
            load_etp(cfg, project_period=PROJECT_PERIOD)


# =====================================================================
# Humidity
# =====================================================================


@pytest.mark.fast
class TestHumidityConfig:
    def test_valid_custom_source(self, tmp_path):
        cfg = HumiditySourceConfig(source="custom", path=tmp_path)
        assert cfg.source == "custom"

    def test_valid_sim2_source(self):
        cfg = HumiditySourceConfig(source="sim2")
        assert cfg.source == "sim2"

    def test_custom_requires_path(self):
        with pytest.raises(ValueError, match="path"):
            HumiditySourceConfig(source="custom")

    def test_invalid_source_rejected(self):
        with pytest.raises(ValueError):
            HumiditySourceConfig(source="era5")

    def test_top_level_config(self, tmp_path):
        cfg = HumidityConfig(
            sources=[HumiditySourceConfig(source="custom", path=tmp_path)],
        )
        assert len(cfg.sources) == 1

    def test_empty_sources_rejected(self):
        with pytest.raises(ValueError):
            HumidityConfig(sources=[])


@pytest.mark.fast
class TestHumidityCustomLoader:
    def test_load_one_station(self, tmp_path):
        d = _make_custom_csv_dir(tmp_path, "humidity", unit="%", value=65.0)
        cfg = HumiditySourceConfig(source="custom", path=d)
        records = load_humidity(cfg, project_period=PROJECT_PERIOD)
        assert len(records) == 1
        assert records[0].variable == "humidity"
        assert records[0].unit == "%"

    def test_missing_loc_file_raises(self, tmp_path):
        d = tmp_path / "humidity_empty"
        d.mkdir()
        cfg = HumiditySourceConfig(source="custom", path=d)
        with pytest.raises(FileNotFoundError, match="humidity_custom_LOC"):
            load_humidity(cfg, project_period=PROJECT_PERIOD)


# =====================================================================
# Precipitation
# =====================================================================


@pytest.mark.fast
class TestPrecipitationConfig:
    def test_valid_custom_source(self, tmp_path):
        cfg = PrecipitationSourceConfig(source="custom", path=tmp_path)
        assert cfg.source == "custom"
        assert cfg.components == ["total"]

    def test_valid_sim2_source(self):
        cfg = PrecipitationSourceConfig(source="sim2")
        assert cfg.source == "sim2"

    def test_custom_requires_path(self):
        with pytest.raises(ValueError, match="path"):
            PrecipitationSourceConfig(source="custom")

    def test_invalid_source_rejected(self):
        with pytest.raises(ValueError):
            PrecipitationSourceConfig(source="gpm")

    def test_components_liquid_solid(self, tmp_path):
        cfg = PrecipitationSourceConfig(
            source="custom",
            path=tmp_path,
            components=["liquid", "solid"],
        )
        assert cfg.components == ["liquid", "solid"]

    def test_invalid_component_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            PrecipitationSourceConfig(
                source="custom",
                path=tmp_path,
                components=["hail"],
            )

    def test_empty_components_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            PrecipitationSourceConfig(
                source="custom",
                path=tmp_path,
                components=[],
            )

    def test_top_level_config(self, tmp_path):
        cfg = PrecipitationConfig(
            sources=[PrecipitationSourceConfig(source="custom", path=tmp_path)],
        )
        assert len(cfg.sources) == 1

    def test_empty_sources_rejected(self):
        with pytest.raises(ValueError):
            PrecipitationConfig(sources=[])


@pytest.mark.fast
class TestPrecipitationCustomLoader:
    def test_load_one_station(self, tmp_path):
        d = _make_custom_csv_dir(tmp_path, "precipitation", unit="mm/day", value=5.0)
        cfg = PrecipitationSourceConfig(source="custom", path=d)
        records = load_precipitation(cfg, project_period=PROJECT_PERIOD)
        assert len(records) == 1
        assert records[0].variable == "precipitation"
        assert records[0].unit == "mm/day"
        assert records[0].data["value"].iloc[0] == pytest.approx(5.0)

    def test_missing_loc_file_raises(self, tmp_path):
        d = tmp_path / "precip_empty"
        d.mkdir()
        cfg = PrecipitationSourceConfig(source="custom", path=d)
        with pytest.raises(FileNotFoundError, match="precipitation_custom_LOC"):
            load_precipitation(cfg, project_period=PROJECT_PERIOD)


# =====================================================================
# Radiation
# =====================================================================


@pytest.mark.fast
class TestRadiationConfig:
    def test_valid_custom_source(self, tmp_path):
        cfg = RadiationSourceConfig(source="custom", path=tmp_path)
        assert cfg.source == "custom"
        assert cfg.components == ["atmospheric", "visible"]

    def test_valid_sim2_source(self):
        cfg = RadiationSourceConfig(source="sim2")
        assert cfg.source == "sim2"

    def test_custom_requires_path(self):
        with pytest.raises(ValueError, match="path"):
            RadiationSourceConfig(source="custom")

    def test_invalid_source_rejected(self):
        with pytest.raises(ValueError):
            RadiationSourceConfig(source="copernicus")

    def test_components_atmospheric_only(self, tmp_path):
        cfg = RadiationSourceConfig(
            source="custom",
            path=tmp_path,
            components=["atmospheric"],
        )
        assert cfg.components == ["atmospheric"]

    def test_invalid_component_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            RadiationSourceConfig(
                source="custom",
                path=tmp_path,
                components=["infrared"],
            )

    def test_top_level_config(self, tmp_path):
        cfg = RadiationConfig(
            sources=[RadiationSourceConfig(source="custom", path=tmp_path)],
        )
        assert len(cfg.sources) == 1

    def test_empty_sources_rejected(self):
        with pytest.raises(ValueError):
            RadiationConfig(sources=[])


@pytest.mark.fast
class TestRadiationCustomLoader:
    def test_load_one_station(self, tmp_path):
        d = _make_custom_csv_dir(tmp_path, "radiation", unit="MJ/m2/j", value=12.0)
        cfg = RadiationSourceConfig(source="custom", path=d)
        records = load_radiation(cfg, project_period=PROJECT_PERIOD)
        assert len(records) == 1
        assert records[0].variable == "radiation"
        assert records[0].unit == "MJ/m2/j"

    def test_missing_loc_file_raises(self, tmp_path):
        d = tmp_path / "radiation_empty"
        d.mkdir()
        cfg = RadiationSourceConfig(source="custom", path=d)
        with pytest.raises(FileNotFoundError, match="radiation_custom_LOC"):
            load_radiation(cfg, project_period=PROJECT_PERIOD)


# =====================================================================
# Recharge
# =====================================================================


@pytest.mark.fast
class TestRechargeConfig:
    def test_valid_custom_source(self, tmp_path):
        cfg = RechargeSourceConfig(source="custom", path=tmp_path)
        assert cfg.source == "custom"

    def test_valid_sim2_source(self):
        cfg = RechargeSourceConfig(source="sim2")
        assert cfg.source == "sim2"

    def test_valid_synthetic_source(self):
        cfg = RechargeSourceConfig(source="synthetic", values=[0.5])
        assert cfg.source == "synthetic"
        assert cfg.values == [0.5]

    def test_custom_requires_path(self):
        with pytest.raises(ValueError, match="path"):
            RechargeSourceConfig(source="custom")

    def test_synthetic_requires_values(self):
        with pytest.raises(ValueError, match="values"):
            RechargeSourceConfig(source="synthetic")

    def test_invalid_source_rejected(self):
        with pytest.raises(ValueError):
            RechargeSourceConfig(source="pyhelp")

    def test_synthetic_with_amplitude(self):
        cfg = RechargeSourceConfig(
            source="synthetic",
            values=[1.0],
            amplitude=0.5,
            period_days=365,
        )
        assert cfg.amplitude == 0.5
        assert cfg.period_days == 365

    def test_top_level_config(self, tmp_path):
        cfg = RechargeConfig(
            sources=[RechargeSourceConfig(source="custom", path=tmp_path)],
        )
        assert len(cfg.sources) == 1

    def test_empty_sources_rejected(self):
        with pytest.raises(ValueError):
            RechargeConfig(sources=[])


@pytest.mark.fast
class TestRechargeCustomLoader:
    def test_load_one_station(self, tmp_path):
        d = _make_custom_csv_dir(tmp_path, "recharge", unit="mm/day", value=0.8)
        cfg = RechargeSourceConfig(source="custom", path=d)
        records = load_recharge(cfg, project_period=PROJECT_PERIOD)
        assert len(records) == 1
        assert records[0].variable == "recharge"
        assert records[0].unit == "mm/day"
        assert records[0].data["value"].iloc[0] == pytest.approx(0.8)

    def test_missing_loc_file_raises(self, tmp_path):
        d = tmp_path / "recharge_empty"
        d.mkdir()
        cfg = RechargeSourceConfig(source="custom", path=d)
        with pytest.raises(FileNotFoundError, match="recharge_custom_LOC"):
            load_recharge(cfg, project_period=PROJECT_PERIOD)


# =====================================================================
# Runoff
# =====================================================================


@pytest.mark.fast
class TestRunoffConfig:
    def test_valid_custom_source(self, tmp_path):
        cfg = RunoffSourceConfig(source="custom", path=tmp_path)
        assert cfg.source == "custom"

    def test_valid_sim2_source(self):
        cfg = RunoffSourceConfig(source="sim2")
        assert cfg.source == "sim2"

    def test_custom_requires_path(self):
        with pytest.raises(ValueError, match="path"):
            RunoffSourceConfig(source="custom")

    def test_invalid_source_rejected(self):
        with pytest.raises(ValueError):
            RunoffSourceConfig(source="hype")

    def test_top_level_config(self, tmp_path):
        cfg = RunoffConfig(
            sources=[RunoffSourceConfig(source="custom", path=tmp_path)],
        )
        assert len(cfg.sources) == 1

    def test_empty_sources_rejected(self):
        with pytest.raises(ValueError):
            RunoffConfig(sources=[])


@pytest.mark.fast
class TestRunoffCustomLoader:
    def test_load_one_station(self, tmp_path):
        d = _make_custom_csv_dir(tmp_path, "runoff", unit="mm/day", value=2.0)
        cfg = RunoffSourceConfig(source="custom", path=d)
        records = load_runoff(cfg, project_period=PROJECT_PERIOD)
        assert len(records) == 1
        assert records[0].variable == "runoff"
        assert records[0].unit == "mm/day"

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

    def test_missing_loc_file_raises(self, tmp_path):
        d = tmp_path / "runoff_empty"
        d.mkdir()
        cfg = RunoffSourceConfig(source="custom", path=d)
        with pytest.raises(FileNotFoundError, match="runoff_custom_LOC"):
            load_runoff(cfg, project_period=PROJECT_PERIOD)


# =====================================================================
# Soil Moisture
# =====================================================================


@pytest.mark.fast
class TestSoilMoistureConfig:
    def test_valid_custom_source(self, tmp_path):
        cfg = SoilMoistureSourceConfig(source="custom", path=tmp_path)
        assert cfg.source == "custom"

    def test_valid_sim2_source(self):
        cfg = SoilMoistureSourceConfig(source="sim2")
        assert cfg.source == "sim2"

    def test_custom_requires_path(self):
        with pytest.raises(ValueError, match="path"):
            SoilMoistureSourceConfig(source="custom")

    def test_invalid_source_rejected(self):
        with pytest.raises(ValueError):
            SoilMoistureSourceConfig(source="smap")

    def test_top_level_config(self, tmp_path):
        cfg = SoilMoistureConfig(
            sources=[SoilMoistureSourceConfig(source="custom", path=tmp_path)],
        )
        assert len(cfg.sources) == 1

    def test_empty_sources_rejected(self):
        with pytest.raises(ValueError):
            SoilMoistureConfig(sources=[])


@pytest.mark.fast
class TestSoilMoistureCustomLoader:
    def test_load_one_station(self, tmp_path):
        d = _make_custom_csv_dir(tmp_path, "soil_moisture", unit="%", value=35.0)
        cfg = SoilMoistureSourceConfig(source="custom", path=d)
        records = load_soil_moisture(cfg, project_period=PROJECT_PERIOD)
        assert len(records) == 1
        assert records[0].variable == "soil_moisture"
        assert records[0].unit == "%"

    def test_missing_loc_file_raises(self, tmp_path):
        d = tmp_path / "soil_moisture_empty"
        d.mkdir()
        cfg = SoilMoistureSourceConfig(source="custom", path=d)
        with pytest.raises(FileNotFoundError, match="soil_moisture_custom_LOC"):
            load_soil_moisture(cfg, project_period=PROJECT_PERIOD)


# =====================================================================
# Temperature
# =====================================================================


@pytest.mark.fast
class TestTemperatureConfig:
    def test_valid_custom_source(self, tmp_path):
        cfg = TemperatureSourceConfig(source="custom", path=tmp_path)
        assert cfg.source == "custom"

    def test_valid_sim2_source(self):
        cfg = TemperatureSourceConfig(source="sim2")
        assert cfg.source == "sim2"

    def test_custom_requires_path(self):
        with pytest.raises(ValueError, match="path"):
            TemperatureSourceConfig(source="custom")

    def test_invalid_source_rejected(self):
        with pytest.raises(ValueError):
            TemperatureSourceConfig(source="ecmwf")

    def test_station_ids_filtering(self, tmp_path):
        cfg = TemperatureSourceConfig(
            source="custom",
            path=tmp_path,
            station_ids=["T01", "T02"],
        )
        assert cfg.station_ids == ["T01", "T02"]

    def test_top_level_config(self, tmp_path):
        cfg = TemperatureConfig(
            sources=[TemperatureSourceConfig(source="custom", path=tmp_path)],
        )
        assert len(cfg.sources) == 1

    def test_empty_sources_rejected(self):
        with pytest.raises(ValueError):
            TemperatureConfig(sources=[])


@pytest.mark.fast
class TestTemperatureCustomLoader:
    def test_load_one_station(self, tmp_path):
        d = _make_custom_csv_dir(tmp_path, "temperature", unit="degC", value=15.0)
        cfg = TemperatureSourceConfig(source="custom", path=d)
        records = load_temperature(cfg, project_period=PROJECT_PERIOD)
        assert len(records) == 1
        assert records[0].variable == "temperature"
        assert records[0].unit == "degC"
        assert records[0].data["value"].iloc[0] == pytest.approx(15.0)

    def test_missing_loc_file_raises(self, tmp_path):
        d = tmp_path / "temperature_empty"
        d.mkdir()
        cfg = TemperatureSourceConfig(source="custom", path=d)
        with pytest.raises(FileNotFoundError, match="temperature_custom_LOC"):
            load_temperature(cfg, project_period=PROJECT_PERIOD)


# =====================================================================
# Wind
# =====================================================================


@pytest.mark.fast
class TestWindConfig:
    def test_valid_custom_source(self, tmp_path):
        cfg = WindSourceConfig(source="custom", path=tmp_path)
        assert cfg.source == "custom"

    def test_valid_sim2_source(self):
        cfg = WindSourceConfig(source="sim2")
        assert cfg.source == "sim2"

    def test_custom_requires_path(self):
        with pytest.raises(ValueError, match="path"):
            WindSourceConfig(source="custom")

    def test_invalid_source_rejected(self):
        with pytest.raises(ValueError):
            WindSourceConfig(source="ncep")

    def test_source_unit_override(self, tmp_path):
        cfg = WindSourceConfig(
            source="custom",
            path=tmp_path,
            source_unit="km/h",
        )
        assert cfg.source_unit == "km/h"

    def test_top_level_config(self, tmp_path):
        cfg = WindConfig(
            sources=[WindSourceConfig(source="custom", path=tmp_path)],
        )
        assert len(cfg.sources) == 1

    def test_empty_sources_rejected(self):
        with pytest.raises(ValueError):
            WindConfig(sources=[])


@pytest.mark.fast
class TestWindCustomLoader:
    def test_load_one_station(self, tmp_path):
        d = _make_custom_csv_dir(tmp_path, "wind", unit="m/s", value=4.2)
        cfg = WindSourceConfig(source="custom", path=d)
        records = load_wind(cfg, project_period=PROJECT_PERIOD)
        assert len(records) == 1
        assert records[0].variable == "wind"
        assert records[0].unit == "m/s"
        assert records[0].data["value"].iloc[0] == pytest.approx(4.2)

    def test_missing_loc_file_raises(self, tmp_path):
        d = tmp_path / "wind_empty"
        d.mkdir()
        cfg = WindSourceConfig(source="custom", path=d)
        with pytest.raises(FileNotFoundError, match="wind_custom_LOC"):
            load_wind(cfg, project_period=PROJECT_PERIOD)
