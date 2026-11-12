"""Unit tests for OceanicConfig and OceanicSourceConfig validation."""

import pytest
from pydantic import ValidationError

from hydromodpy.data.variables.oceanic.config import OceanicConfig, OceanicSourceConfig


@pytest.mark.fast
class TestOceanicSourceConfig:
    def test_constant_source_requires_value(self):
        with pytest.raises(ValidationError, match="Constant source requires 'value'"):
            OceanicSourceConfig(source="constant")

    def test_custom_source_requires_path(self):
        with pytest.raises(ValidationError, match="File source requires 'path'"):
            OceanicSourceConfig(source="file")


@pytest.mark.fast
class TestOceanicConfig:
    def test_invalid_date_format(self):
        with pytest.raises(ValidationError, match="Invalid ISO date"):
            OceanicConfig(
                sources=[{"source": "constant", "value": 0.0}],
                date_start="01-01-2003",
            )
