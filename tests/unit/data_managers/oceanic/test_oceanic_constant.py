"""Unit tests for oceanic constant source generation."""

from datetime import datetime

import pytest

from hydromodpy.data.variables.oceanic.config import OceanicSourceConfig
from hydromodpy.data.variables.oceanic.constant import generate_constant


@pytest.mark.fast
class TestGenerateConstant:
    def test_generates_single_point_record(self):
        cfg = OceanicSourceConfig(source="constant", value=0.0)
        records = generate_constant(cfg)
        assert len(records) == 1
        rec = records[0]
        assert rec.station_id == "constant"
        assert rec.variable == "mean_sea_level"
        assert rec.source == "constant"
        assert rec.unit == "m"
        assert rec.is_constant is True
        assert rec.data["value"].iloc[0] == 0.0

    def test_nonzero_value(self):
        cfg = OceanicSourceConfig(source="constant", value=3.5)
        records = generate_constant(cfg)
        assert records[0].data["value"].iloc[0] == 3.5

    def test_expands_with_project_period(self):
        cfg = OceanicSourceConfig(source="constant", value=1.0)
        period = (datetime(2003, 1, 1), datetime(2003, 1, 10))
        records = generate_constant(cfg, project_period=period)
        rec = records[0]
        assert len(rec.data) == 10
        assert all(rec.data["value"] == 1.0)
        assert rec.date_start == datetime(2003, 1, 1)
        assert rec.date_end == datetime(2003, 1, 10)

    def test_without_project_period(self):
        cfg = OceanicSourceConfig(source="constant", value=2.0)
        records = generate_constant(cfg)
        assert len(records[0].data) == 1
