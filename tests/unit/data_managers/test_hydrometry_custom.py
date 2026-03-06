"""Tests for hydrometry custom loader."""

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.data_managers.hydrometry.config import HydrometrySourceConfig, HydrometryConfig
from hydromodpy.data_managers.hydrometry.custom import load_custom


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

    def test_unit_conversion(self, sample_hydro_dir, project_period):
        cfg = HydrometrySourceConfig(
            source="custom", path=sample_hydro_dir,
            source_unit="L/s", target_unit="m3/s",
        )
        records = load_custom(cfg, project_period=project_period)
        # ST001 has value 2.5 L/s → 0.0025 m³/s
        st1 = [r for r in records if r.station_id == "ST001"][0]
        assert st1.data["value"].iloc[0] == pytest.approx(0.0025)


class TestHydrometryCustomConstant:
    def test_single_line_csv(self, tmp_path, project_period):
        d = tmp_path / "const"
        d.mkdir()

        pd.DataFrame({"id": ["C1"], "x": [0], "y": [0], "crs": ["EPSG:4326"]}).to_csv(
            d / "hydrometry_custom_LOC.csv", index=False
        )
        pd.DataFrame({"datetime": ["2020-01-01"], "value": [9.9]}).to_csv(
            d / "hydrometry_custom_C1_20200101_20200331_D.csv", index=False
        )

        cfg = HydrometrySourceConfig(source="custom", path=d)
        records = load_custom(cfg, project_period=project_period)

        assert len(records) == 1
        assert records[0].is_constant
        assert records[0].n_records == 91  # Jan-Mar 2020

    def test_fixed_values_config(self, project_period):
        cfg = HydrometrySourceConfig(
            source="custom",
            fixed_values={"A": 1.0, "B": 2.0},
        )
        records = load_custom(cfg, project_period=project_period)
        assert len(records) == 2
        assert all(r.is_constant for r in records)

    def test_fixed_value_requires_period(self):
        cfg = HydrometrySourceConfig(
            source="custom", fixed_value=1.0, station_ids=["X"],
        )
        with pytest.raises(ValueError, match="project_period"):
            load_custom(cfg, project_period=None)


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
