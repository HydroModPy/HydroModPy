"""Tests for water quality custom loader."""

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.data_managers.water_quality.config import WaterQualitySourceConfig
from hydromodpy.data_managers.water_quality.custom import load_custom


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
            source="custom", path=sample_wq_dir,
            station_ids=["SITE02"],
        )
        records = load_custom(cfg, project_period=project_period)
        assert len(records) == 1
        assert records[0].station_id == "SITE02"


class TestWaterQualityCustomConstant:
    def test_fixed_values(self, project_period):
        cfg = WaterQualitySourceConfig(
            source="custom",
            fixed_values={"S1": 7.0, "S2": 6.5},
            source_unit="mg/L",
        )
        records = load_custom(cfg, project_period=project_period)
        assert len(records) == 2
        assert records[0].is_constant
        assert records[0].data["value"].iloc[0] == pytest.approx(7.0)
