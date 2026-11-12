"""Tests for hydrometry file loader."""

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.core.exceptions import DataSourceError
from hydromodpy.data.variables.hydrometry.config import HydrometryConfig, HydrometrySourceConfig
from hydromodpy.data.variables.hydrometry.variable import HydrometryVariable


def _load_file(cfg, *, project_period=None):
    """Load one custom source the way the hydrometry manager does."""
    mgr = HydrometryVariable(config=None, index=None, project_period=project_period)
    fn = getattr(mgr, "load_file", getattr(mgr, "load_file", None))
    return fn(cfg)


class TestHydrometryFileCSV:
    def test_filter_station_ids(self, sample_hydro_dir, project_period):
        cfg = HydrometrySourceConfig(source="file", path=sample_hydro_dir, station_ids=["ST001"])
        records = _load_file(cfg, project_period=project_period)
        assert len(records) == 1
        assert records[0].station_id == "ST001"

    def test_an_unknown_station_id_is_refused(self, sample_hydro_dir, project_period):
        # Dropping it silently leaves an empty observed series, and a
        # calibration scored against nothing still reports a number.
        cfg = HydrometrySourceConfig(source="file", path=sample_hydro_dir, station_ids=["ST999"])

        with pytest.raises(DataSourceError, match="ST999"):
            _load_file(cfg, project_period=project_period)

    def test_the_refusal_names_the_ids_the_file_does_hold(self, sample_hydro_dir, project_period):
        cfg = HydrometrySourceConfig(
            source="file", path=sample_hydro_dir, station_ids=["ST001", "NANCON"]
        )

        with pytest.raises(DataSourceError) as excinfo:
            _load_file(cfg, project_period=project_period)

        message = str(excinfo.value)
        assert "NANCON" in message
        assert "ST001" in message

    @pytest.mark.parametrize("source_unit", ["L/s", "l/s"])
    def test_unit_conversion_via_loc(self, tmp_path, project_period, source_unit):
        """Unit from LOC column; conversion L/s and l/s -> m3/s."""
        d = tmp_path / "hydro_ls"
        d.mkdir()

        pd.DataFrame(
            {
                "id": ["ST_LS"],
                "x": [-1.5],
                "y": [48.1],
                "crs": ["EPSG:4326"],
                "unit": [source_unit],
            }
        ).to_csv(d / "hydrometry_custom_LOC.csv", index=False)

        dates = pd.date_range("2020-01-01", "2020-03-31", freq="D")
        pd.DataFrame({"datetime": dates, "value": 2500.0}).to_csv(
            d / "hydrometry_custom_ST_LS_20200101_20200331_D.csv",
            index=False,
        )

        cfg = HydrometrySourceConfig(source="file", path=d)
        records = _load_file(cfg, project_period=project_period)
        # 2500 L/s -> 2.5 m3/s
        assert records[0].data["value"].iloc[0] == pytest.approx(2.5)
        assert records[0].unit == "m3/s"
        assert records[0].source_unit == source_unit

    def test_missing_unit_raises(self, tmp_path, project_period):
        """LOC without 'unit' column must raise ValueError."""
        d = tmp_path / "no_unit"
        d.mkdir()

        pd.DataFrame(
            {
                "id": ["ST01"],
                "x": [-1.5],
                "y": [48.1],
                "crs": ["EPSG:4326"],
            }
        ).to_csv(d / "hydrometry_custom_LOC.csv", index=False)

        dates = pd.date_range("2020-01-01", "2020-03-31", freq="D")
        pd.DataFrame({"datetime": dates, "value": 1.0}).to_csv(
            d / "hydrometry_custom_ST01_20200101_20200331_D.csv",
            index=False,
        )

        cfg = HydrometrySourceConfig(source="file", path=d)
        with pytest.raises(ValueError, match="No unit"):
            _load_file(cfg, project_period=project_period)


class TestHydrometryFileErrors:
    def test_missing_directory(self, project_period):
        cfg = HydrometrySourceConfig(source="file", path=Path("/nonexistent"))
        with pytest.raises(FileNotFoundError):
            _load_file(cfg, project_period=project_period)

    def test_custom_requires_path(self):
        with pytest.raises(ValueError, match="path"):
            HydrometrySourceConfig(source="file")


class TestHydrometrySourceConfigDeclaredDefaults:
    """The generator writes declared defaults; they have to form a valid entry."""

    def test_default_source_is_hubeau(self):
        assert HydrometrySourceConfig.model_fields["source"].default == "hubeau"

    def test_default_product_is_qmnj(self):
        assert HydrometrySourceConfig.model_fields["product"].default == "QmnJ"


def _station_folder(tmp_path, *, loc_unit=None):
    folder = tmp_path / "hydro_cfg_unit"
    folder.mkdir()
    loc = {"id": ["ST01"], "x": [-1.5], "y": [48.1], "crs": ["EPSG:4326"]}
    if loc_unit is not None:
        loc["unit"] = [loc_unit]
    pd.DataFrame(loc).to_csv(folder / "hydrometry_custom_LOC.csv", index=False)
    dates = pd.date_range("2020-01-01", "2020-03-31", freq="D")
    pd.DataFrame({"datetime": dates, "value": 2500.0}).to_csv(
        folder / "hydrometry_custom_ST01_20200101_20200331_D.csv", index=False
    )
    return folder


def test_the_source_unit_of_the_config_converts_a_folder_without_loc_units(tmp_path):
    cfg = HydrometrySourceConfig(source="file", path=_station_folder(tmp_path), source_unit="L/s")
    records = _load_file(cfg)
    assert records[0].data["value"].iloc[0] == pytest.approx(2.5)
    assert records[0].source_unit == "L/s"


def test_a_source_unit_that_contradicts_the_loc_unit_is_refused(tmp_path):
    cfg = HydrometrySourceConfig(
        source="file", path=_station_folder(tmp_path, loc_unit="m3/s"), source_unit="L/s"
    )
    with pytest.raises(ValueError, match="source_unit"):
        _load_file(cfg)
