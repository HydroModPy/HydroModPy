"""Tests for common/unit_helpers."""

import pytest

from hydromodpy.data_managers.common.unit_helpers import convert_value, get_conversion_factor


class TestUnitConversion:
    def test_identity(self):
        assert convert_value(5.0, "m3/s", "m3/s") == 5.0

    def test_ls_to_m3s(self):
        assert convert_value(1000.0, "L/s", "m3/s") == pytest.approx(1.0)

    def test_m3s_to_ls(self):
        assert convert_value(1.0, "m3/s", "L/s") == pytest.approx(1000.0)

    def test_cm_to_m(self):
        assert convert_value(100.0, "cm", "m") == pytest.approx(1.0)

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown unit"):
            convert_value(1.0, "gallons", "m3/s")

    def test_factor_identity(self):
        assert get_conversion_factor("m", "m") == 1.0
