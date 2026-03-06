"""Tests for piezometry custom loader."""

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.data_managers.piezometry.config import PiezometrySourceConfig
from hydromodpy.data_managers.piezometry.custom import load_custom


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
    def test_fixed_values(self, project_period):
        cfg = PiezometrySourceConfig(
            source="custom",
            fixed_values={"PZ1": 10.0},
            product=None,
        )
        records = load_custom(cfg, project_period=project_period)
        assert len(records) == 1
        assert records[0].is_constant
        assert records[0].data["value"].iloc[0] == pytest.approx(10.0)
