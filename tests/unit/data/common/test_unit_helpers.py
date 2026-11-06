"""Tests for common/unit_helpers."""

import numpy as np
import pandas as pd
import pytest

from hydromodpy.data.common.unit_helpers import (
    convert_array,
    convert_value,
    get_conversion_factor,
)


class TestUnitConversion:
    @pytest.mark.parametrize(
        ("value", "from_unit", "to_unit", "expected"),
        [
            (5.0, "m3/s", "m3/s", 5.0),
            (1000.0, "L/s", "m3/s", 1.0),
            (1000.0, "l/s", "m3/s", 1.0),  # lowercase unit alias
            (1.0, "m3/s", "L/s", 1000.0),
            (100.0, "cm", "m", 1.0),
            (12.5, "C", "degC", 12.5),  # bare "C" alias
            (2500.0, "ug/l", "mg/L", 2.5),
        ],
        ids=[
            "identity",
            "ls_to_m3s",
            "lowercase_ls_to_m3s",
            "m3s_to_ls",
            "cm_to_m",
            "c_alias_to_degc",
            "ug_l_alias_to_mg_l",
        ],
    )
    def test_value_conversions(self, value, from_unit, to_unit, expected):
        assert convert_value(value, from_unit, to_unit) == pytest.approx(expected)

    @pytest.mark.parametrize(
        ("from_unit", "to_unit", "expected"),
        [
            ("mm/d", "mm/day", 1.0),  # alias, same unit
            ("MJ/m2/day", "MJ/m2/j", 1.0),  # alias, same unit
            ("m", "m", 1.0),
        ],
        ids=["mm_d_alias_to_mm_day", "radiation_day_alias_to_j", "factor_identity"],
    )
    def test_factor_conversions(self, from_unit, to_unit, expected):
        assert get_conversion_factor(from_unit, to_unit) == pytest.approx(expected)

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown unit"):
            convert_value(1.0, "gallons", "m3/s")


# ------------------------------------------------------------------
# Temperature (affine conversions)
# ------------------------------------------------------------------


class TestTemperatureConversion:
    @pytest.mark.parametrize(
        ("value", "from_unit", "to_unit", "expected"),
        [
            (273.15, "K", "degC", 0.0),
            (0.0, "degC", "K", 273.15),
            (373.15, "K", "degC", 100.0),
            (32.0, "degF", "degC", 0.0),
            (212.0, "degF", "degC", 100.0),
            (100.0, "degC", "degF", 212.0),
            (273.15, "K", "degF", 32.0),
        ],
        ids=[
            "kelvin_to_degc",
            "degc_to_kelvin",
            "kelvin_to_degc_boiling",
            "fahrenheit_to_degc_freezing",
            "fahrenheit_to_degc_boiling",
            "degc_to_fahrenheit",
            "kelvin_to_fahrenheit",
        ],
    )
    def test_temperature_conversions(self, value, from_unit, to_unit, expected):
        assert convert_value(value, from_unit, to_unit) == pytest.approx(expected)

    def test_factor_raises_for_offset(self):
        with pytest.raises(TypeError, match="offset"):
            get_conversion_factor("K", "degC")


# ------------------------------------------------------------------
# Radiation
# ------------------------------------------------------------------


class TestRadiationConversion:
    @pytest.mark.parametrize(
        ("value", "from_unit", "to_unit", "expected"),
        [
            # 1 MJ/m2/day = 1e6 / 86400 W/m2 ~= 11.5741
            (1.0, "MJ/m2/day", "W/m2", 1.0e6 / 86400.0),
            (1.0e6 / 86400.0, "W/m2", "MJ/m2/day", 1.0),
            # 1 J/cm2/day = 1e4 / 86400 W/m2 ~= 0.115741
            (1.0, "J/cm2/day", "W/m2", 1.0e4 / 86400.0),
            # 1 cal/cm2/day = 4.184e4 / 86400 W/m2 ~= 0.484259
            (1.0, "cal/cm2/day", "W/m2", 4.184e4 / 86400.0),
            (1.0, "kWh/m2/day", "W/m2", 3.6e6 / 86400.0),
            (10.0, "W/m^2", "W/m2", 10.0),  # caret alias
            (1.0, "ly/day", "cal/cm2/day", 1.0),  # langley alias
        ],
        ids=[
            "mj_m2_day_to_w_m2",
            "w_m2_to_mj_m2_day",
            "j_cm2_day_to_w_m2",
            "cal_cm2_day_to_w_m2",
            "kwh_m2_day_to_w_m2",
            "radiation_alias_wm2",
            "radiation_alias_langley",
        ],
    )
    def test_radiation_conversions(self, value, from_unit, to_unit, expected):
        assert convert_value(value, from_unit, to_unit) == pytest.approx(expected)


# ------------------------------------------------------------------
# Percent / fraction
# ------------------------------------------------------------------


class TestPercentConversion:
    @pytest.mark.parametrize(
        ("value", "from_unit", "to_unit", "expected"),
        [
            (0.5, "fraction", "%", 50.0),
            (75.0, "%", "fraction", 0.75),
            (1.0, "ratio", "%", 100.0),
        ],
        ids=["fraction_to_percent", "percent_to_fraction", "ratio_to_percent"],
    )
    def test_percent_conversions(self, value, from_unit, to_unit, expected):
        assert convert_value(value, from_unit, to_unit) == pytest.approx(expected)


# ------------------------------------------------------------------
# Concentration
# ------------------------------------------------------------------


class TestConcentrationConversion:
    @pytest.mark.parametrize(
        ("value", "from_unit", "to_unit", "expected"),
        [
            (1.0, "g/L", "mg/L", 1000.0),
            (1.0e6, "ng/L", "mg/L", 1.0),
            (1.0e6, "ug/L", "g/L", 1.0),
        ],
        ids=["g_l_to_mg_l", "ng_l_to_mg_l", "ug_l_to_g_l"],
    )
    def test_concentration_conversions(self, value, from_unit, to_unit, expected):
        assert convert_value(value, from_unit, to_unit) == pytest.approx(expected)


# ------------------------------------------------------------------
# CF-convention remapping
# ------------------------------------------------------------------


class TestCFConventionUnits:
    @pytest.mark.parametrize(
        ("value", "from_unit", "to_unit", "expected"),
        [
            # "kg m-2 s-1" is CF precip mass flux, remapped to mm/s
            (1.0, "kg m-2 s-1", "mm/s", 1.0),
            (0.01, "kg/kg", "fraction", 0.01),
            (0.5, "kg/kg", "%", 50.0),
        ],
        ids=["kgm2s_to_mm_s", "kgkg_to_fraction", "kgkg_to_percent"],
    )
    def test_cf_conversions(self, value, from_unit, to_unit, expected):
        assert convert_value(value, from_unit, to_unit) == pytest.approx(expected)


# ------------------------------------------------------------------
# Cross-family rejection
# ------------------------------------------------------------------


class TestCrossFamilyRejection:
    @pytest.mark.parametrize(
        ("from_unit", "to_unit"),
        [("m", "m3/s"), ("degC", "%")],
        ids=["length_vs_flow", "temperature_vs_percent"],
    )
    def test_incompatible_families_raise(self, from_unit, to_unit):
        with pytest.raises(ValueError, match="Incompatible"):
            convert_value(1.0, from_unit, to_unit)


# ------------------------------------------------------------------
# convert_array
# ------------------------------------------------------------------


class TestConvertArray:
    def test_numpy_multiplicative(self):
        arr = np.array([1.0, 2.0, 3.0])
        result = convert_array(arr, "cm", "m")
        np.testing.assert_allclose(result, [0.01, 0.02, 0.03])

    def test_numpy_affine_kelvin(self):
        arr = np.array([273.15, 373.15])
        result = convert_array(arr, "K", "degC")
        np.testing.assert_allclose(result, [0.0, 100.0])

    def test_pandas_series(self):
        s = pd.Series([32.0, 212.0])
        result = convert_array(s, "degF", "degC")
        pd.testing.assert_series_equal(
            result,
            pd.Series([0.0, 100.0]),
            atol=1e-10,
        )

    def test_identity_returns_same_object(self):
        arr = np.array([1.0, 2.0])
        result = convert_array(arr, "m", "m")
        assert result is arr
