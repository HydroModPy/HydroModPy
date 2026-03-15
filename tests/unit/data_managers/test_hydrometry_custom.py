"""Tests for hydrometry custom loader."""

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.data_managers.variables.hydrometry.config import HydrometrySourceConfig, HydrometryConfig
from hydromodpy.data_managers.variables.hydrometry.custom import load_custom


class TestHydrometryCustomCSV:
    def test_load_two_stations(self, sample_hydro_dir, project_period):
        cfg = HydrometrySourceConfig(source="custom", path=sample_hydro_dir)
        records = load_custom(cfg, project_period=project_period)

        assert len(records) == 2
        ids = {r.station_id for r in records}
        assert ids == {"ST001", "ST002"}

        for r in records:
            assert r.variable == "discharge"
            assert r.source == "custom"
            assert r.unit == "m3/s"
            assert r.has_data
            assert r.location is not None
            assert r.location.crs == "EPSG:4326"

    def test_filter_station_ids(self, sample_hydro_dir, project_period):
        cfg = HydrometrySourceConfig(
            source="custom", path=sample_hydro_dir, station_ids=["ST001"]
        )
        records = load_custom(cfg, project_period=project_period)
        assert len(records) == 1
        assert records[0].station_id == "ST001"

    def test_unit_conversion_via_loc(self, tmp_path, project_period):
        """Unit from LOC column; conversion L/s -> m3/s."""
        d = tmp_path / "hydro_ls"
        d.mkdir()

        pd.DataFrame({
            "id": ["ST_LS"],
            "x": [-1.5],
            "y": [48.1],
            "crs": ["EPSG:4326"],
            "unit": ["L/s"],
        }).to_csv(d / "hydrometry_custom_LOC.csv", index=False)

        dates = pd.date_range("2020-01-01", "2020-03-31", freq="D")
        pd.DataFrame({"datetime": dates, "value": 2500.0}).to_csv(
            d / "hydrometry_custom_ST_LS_20200101_20200331_D.csv", index=False,
        )

        cfg = HydrometrySourceConfig(source="custom", path=d)
        records = load_custom(cfg, project_period=project_period)
        # 2500 L/s -> 2.5 m3/s
        assert records[0].data["value"].iloc[0] == pytest.approx(2.5)
        assert records[0].unit == "m3/s"

    def test_missing_unit_raises(self, tmp_path, project_period):
        """LOC without 'unit' column must raise ValueError."""
        d = tmp_path / "no_unit"
        d.mkdir()

        pd.DataFrame({
            "id": ["ST01"], "x": [-1.5], "y": [48.1], "crs": ["EPSG:4326"],
        }).to_csv(d / "hydrometry_custom_LOC.csv", index=False)

        dates = pd.date_range("2020-01-01", "2020-03-31", freq="D")
        pd.DataFrame({"datetime": dates, "value": 1.0}).to_csv(
            d / "hydrometry_custom_ST01_20200101_20200331_D.csv", index=False,
        )

        cfg = HydrometrySourceConfig(source="custom", path=d)
        with pytest.raises(ValueError, match="No unit"):
            load_custom(cfg, project_period=project_period)


class TestHydrometryCustomConstant:
    def test_single_line_csv(self, tmp_path, project_period):
        d = tmp_path / "const"
        d.mkdir()

        pd.DataFrame({
            "id": ["C1"], "x": [0], "y": [0], "crs": ["EPSG:4326"], "unit": ["m3/s"],
        }).to_csv(d / "hydrometry_custom_LOC.csv", index=False)

        pd.DataFrame({"datetime": ["2020-01-01"], "value": [9.9]}).to_csv(
            d / "hydrometry_custom_C1_20200101_20200331_D.csv", index=False
        )

        cfg = HydrometrySourceConfig(source="custom", path=d)
        records = load_custom(cfg, project_period=project_period)

        assert len(records) == 1
        assert records[0].is_constant
        assert records[0].n_records == 91  # Jan-Mar 2020


class TestHydrometryCustomErrors:
    def test_missing_directory(self, project_period):
        cfg = HydrometrySourceConfig(source="custom", path=Path("/nonexistent"))
        with pytest.raises(FileNotFoundError):
            load_custom(cfg, project_period=project_period)

    def test_missing_location_file(self, tmp_path, project_period):
        d = tmp_path / "empty"
        d.mkdir()
        cfg = HydrometrySourceConfig(source="custom", path=d)
        with pytest.raises(FileNotFoundError, match="hydrometry_custom_LOC"):
            load_custom(cfg, project_period=project_period)

    def test_custom_requires_path(self):
        with pytest.raises(ValueError, match="path"):
            HydrometrySourceConfig(source="custom")
