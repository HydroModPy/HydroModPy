"""Tests for water quality custom loader."""

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.data.variables.water_quality.config import WaterQualitySourceConfig
from hydromodpy.data.variables.water_quality.custom import load_custom


class TestWaterQualityCustomCSV:
    def test_load_two_sites(self, sample_wq_dir, project_period):
        cfg = WaterQualitySourceConfig(source="custom", path=sample_wq_dir)
        records = load_custom(cfg, project_period=project_period)

        assert len(records) == 2
        for r in records:
            assert r.variable == "water_quality"
            assert r.source == "custom"
            assert r.unit == "mg/L"
            assert r.has_data

    def test_filter_ids(self, sample_wq_dir, project_period):
        cfg = WaterQualitySourceConfig(
            source="custom",
            path=sample_wq_dir,
            station_ids=["SITE02"],
        )
        records = load_custom(cfg, project_period=project_period)
        assert len(records) == 1
        assert records[0].station_id == "SITE02"


class TestWaterQualityCustomConstant:
    def test_single_line_csv(self, tmp_path, project_period):
        d = tmp_path / "const_wq"
        d.mkdir()

        pd.DataFrame(
            {
                "id": ["S1"],
                "x": [2.35],
                "y": [48.85],
                "crs": ["EPSG:4326"],
                "unit": ["mg/L"],
            }
        ).to_csv(d / "waterquality_custom_LOC.csv", index=False)

        pd.DataFrame({"datetime": ["2020-01-01"], "value": [7.0]}).to_csv(
            d / "waterquality_custom_S1_20200101_20200331_D.csv", index=False
        )

        cfg = WaterQualitySourceConfig(source="custom", path=d)
        records = load_custom(cfg, project_period=project_period)
        assert len(records) == 1
        assert records[0].is_constant
        assert records[0].data["value"].iloc[0] == pytest.approx(7.0)

    def test_unit_conversion_ug_l_to_mg_l(self, tmp_path, project_period):
        d = tmp_path / "const_wq_ug"
        d.mkdir()

        pd.DataFrame(
            {
                "id": ["S_UG"],
                "x": [2.35],
                "y": [48.85],
                "crs": ["EPSG:4326"],
                "unit": ["ug/l"],
            }
        ).to_csv(d / "waterquality_custom_LOC.csv", index=False)

        pd.DataFrame({"datetime": ["2020-01-01"], "value": [2500.0]}).to_csv(
            d / "waterquality_custom_S_UG_20200101_20200331_D.csv", index=False
        )

        cfg = WaterQualitySourceConfig(source="custom", path=d)
        records = load_custom(cfg, project_period=project_period)

        assert len(records) == 1
        assert records[0].data["value"].iloc[0] == pytest.approx(2.5)
        assert records[0].unit == "mg/L"
        assert records[0].source_unit == "ug/l"
