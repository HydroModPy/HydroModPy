"""Unit tests for OceanicConfig and OceanicSourceConfig validation."""

import pytest
from pydantic import ValidationError

from hydromodpy.data_managers.variables.oceanic.config import OceanicConfig, OceanicSourceConfig


@pytest.mark.fast
class TestOceanicSourceConfig:
    def test_constant_source_valid(self):
        cfg = OceanicSourceConfig(source="constant", value=0.0)
        assert cfg.source == "constant"
        assert cfg.value == 0.0

    def test_constant_source_requires_value(self):
        with pytest.raises(ValidationError, match="Constant source requires 'value'"):
            OceanicSourceConfig(source="constant")

    def test_custom_source_valid(self, tmp_path):
        cfg = OceanicSourceConfig(source="custom", path=tmp_path)
        assert cfg.source == "custom"
        assert cfg.path == tmp_path

    def test_custom_source_requires_path(self):
        with pytest.raises(ValidationError, match="Custom source requires 'path'"):
            OceanicSourceConfig(source="custom")

    def test_shom_source_valid(self):
        cfg = OceanicSourceConfig(source="shom")
        assert cfg.source == "shom"
        assert cfg.nearest is True

    def test_shom_custom_radius(self):
        cfg = OceanicSourceConfig(source="shom", fallback_search_radius_km=50.0)
        assert cfg.fallback_search_radius_km == 50.0

    def test_invalid_source_rejected(self):
        with pytest.raises(ValidationError):
            OceanicSourceConfig(source="invalid")

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            OceanicSourceConfig(source="constant", value=0.0, unknown_field=True)


@pytest.mark.fast
class TestOceanicConfig:
    def test_single_constant_source(self):
        cfg = OceanicConfig(sources=[{"source": "constant", "value": 0.0}])
        assert len(cfg.sources) == 1
        assert cfg.sources[0].source == "constant"

    def test_multiple_sources(self, tmp_path):
        cfg = OceanicConfig(sources=[
            {"source": "constant", "value": 0.0},
            {"source": "custom", "path": str(tmp_path)},
        ])
        assert len(cfg.sources) == 2

    def test_empty_sources_rejected(self):
        with pytest.raises(ValidationError):
            OceanicConfig(sources=[])

    def test_valid_dates(self):
        cfg = OceanicConfig(
            sources=[{"source": "constant", "value": 0.0}],
            date_start="2003-01-01",
            date_end="2003-01-30",
        )
        assert cfg.date_start == "2003-01-01"
        assert cfg.date_end == "2003-01-30"

    def test_invalid_date_format(self):
        with pytest.raises(ValidationError, match="Invalid ISO date"):
            OceanicConfig(
                sources=[{"source": "constant", "value": 0.0}],
                date_start="01-01-2003",
            )

    def test_date_order_check(self):
        with pytest.raises(ValidationError, match="date_start must be before date_end"):
            OceanicConfig(
                sources=[{"source": "constant", "value": 0.0}],
                date_start="2003-02-01",
                date_end="2003-01-01",
            )

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            OceanicConfig(
                sources=[{"source": "constant", "value": 0.0}],
                msl_source="auto",
            )
