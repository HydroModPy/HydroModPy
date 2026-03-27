"""Tests for piezometry custom loader."""

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.data.variables.piezometry.config import PiezometrySourceConfig
from hydromodpy.data.variables.piezometry.custom import load_custom


class TestPiezometryCustomCSV:
    def test_load_two_piezometers(self, sample_piezo_dir, project_period):
        cfg = PiezometrySourceConfig(source="custom", path=sample_piezo_dir, product=None)
        records = load_custom(cfg, project_period=project_period)

        assert len(records) == 2
        for r in records:
            assert r.variable == "groundwater_level"
            assert r.source == "custom"
            assert r.unit == "m"
            assert r.has_data

    def test_filter_ids(self, sample_piezo_dir, project_period):
        cfg = PiezometrySourceConfig(
            source="custom", path=sample_piezo_dir,
            station_ids=["BSS002"], product=None,
        )
        records = load_custom(cfg, project_period=project_period)
        assert len(records) == 1
        assert records[0].station_id == "BSS002"


class TestPiezometryCustomConstant:
    def test_single_line_csv(self, tmp_path, project_period):
        d = tmp_path / "const_piezo"
        d.mkdir()

        pd.DataFrame({
            "id": ["PZ1"], "x": [0], "y": [0], "crs": ["EPSG:4326"], "unit": ["m"],
        }).to_csv(d / "piezometry_custom_LOC.csv", index=False)

        pd.DataFrame({"datetime": ["2020-01-01"], "value": [10.0]}).to_csv(
            d / "piezometry_custom_PZ1_20200101_20200331_D.csv", index=False
        )

        cfg = PiezometrySourceConfig(source="custom", path=d, product=None)
        records = load_custom(cfg, project_period=project_period)
        assert len(records) == 1
        assert records[0].is_constant
        assert records[0].data["value"].iloc[0] == pytest.approx(10.0)

    def test_unit_conversion_cm_to_m(self, tmp_path, project_period):
        d = tmp_path / "piezo_cm"
        d.mkdir()

        pd.DataFrame({
            "id": ["PZ_CM"], "x": [0], "y": [0], "crs": ["EPSG:4326"], "unit": ["cm"],
        }).to_csv(d / "piezometry_custom_LOC.csv", index=False)

        pd.DataFrame({"datetime": ["2020-01-01"], "value": [250.0]}).to_csv(
            d / "piezometry_custom_PZ_CM_20200101_20200331_D.csv", index=False
        )

        cfg = PiezometrySourceConfig(source="custom", path=d, product=None)
        records = load_custom(cfg, project_period=project_period)

        assert len(records) == 1
        assert records[0].data["value"].iloc[0] == pytest.approx(2.5)
        assert records[0].unit == "m"
        assert records[0].source_unit == "cm"
