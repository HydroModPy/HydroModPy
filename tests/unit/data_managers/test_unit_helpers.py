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
    def test_identity(self):
        assert convert_value(5.0, "m3/s", "m3/s") == 5.0

    def test_ls_to_m3s(self):
        assert convert_value(1000.0, "L/s", "m3/s") == pytest.approx(1.0)

    def test_lowercase_ls_to_m3s(self):
        assert convert_value(1000.0, "l/s", "m3/s") == pytest.approx(1.0)

    def test_m3s_to_ls(self):
        assert convert_value(1.0, "m3/s", "L/s") == pytest.approx(1000.0)

    def test_cm_to_m(self):
        assert convert_value(100.0, "cm", "m") == pytest.approx(1.0)

    def test_mm_d_alias_to_mm_day(self):
        assert get_conversion_factor("mm/d", "mm/day") == pytest.approx(1.0)

    def test_c_alias_to_degc(self):
        assert convert_value(12.5, "C", "degC") == pytest.approx(12.5)

    def test_ug_l_alias_to_mg_l(self):
        assert convert_value(2500.0, "ug/l", "mg/L") == pytest.approx(2.5)

    def test_radiation_day_alias_to_j(self):
        assert get_conversion_factor("MJ/m2/day", "MJ/m2/j") == pytest.approx(1.0)

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown unit"):
            convert_value(1.0, "gallons", "m3/s")

    def test_factor_identity(self):
        assert get_conversion_factor("m", "m") == 1.0


# ------------------------------------------------------------------
# Temperature (affine conversions)
# ------------------------------------------------------------------


class TestTemperatureConversion:
    def test_kelvin_to_degc(self):
        assert convert_value(273.15, "K", "degC") == pytest.approx(0.0)

    def test_degc_to_kelvin(self):
        assert convert_value(0.0, "degC", "K") == pytest.approx(273.15)

    def test_kelvin_to_degc_boiling(self):
        assert convert_value(373.15, "K", "degC") == pytest.approx(100.0)

    def test_fahrenheit_to_degc_freezing(self):
        assert convert_value(32.0, "degF", "degC") == pytest.approx(0.0)

    def test_fahrenheit_to_degc_boiling(self):
        assert convert_value(212.0, "degF", "degC") == pytest.approx(100.0)

    def test_degc_to_fahrenheit(self):
        assert convert_value(100.0, "degC", "degF") == pytest.approx(212.0)

    def test_kelvin_to_fahrenheit(self):
        assert convert_value(273.15, "K", "degF") == pytest.approx(32.0)

    def test_factor_raises_for_offset(self):
        with pytest.raises(TypeError, match="offset"):
            get_conversion_factor("K", "degC")


# ------------------------------------------------------------------
# Radiation
# ------------------------------------------------------------------


class TestRadiationConversion:
    def test_mj_m2_day_to_w_m2(self):
        # 1 MJ/m2/day = 1e6 / 86400 W/m2 ≈ 11.5741
        assert convert_value(1.0, "MJ/m2/day", "W/m2") == pytest.approx(
            1.0e6 / 86400.0,
        )

    def test_w_m2_to_mj_m2_day(self):
        assert convert_value(1.0e6 / 86400.0, "W/m2", "MJ/m2/day") == pytest.approx(1.0)

    def test_j_cm2_day_to_w_m2(self):
        # 1 J/cm2/day = 1e4 / 86400 W/m2 ≈ 0.115741
        assert convert_value(1.0, "J/cm2/day", "W/m2") == pytest.approx(
            1.0e4 / 86400.0,
        )

    def test_cal_cm2_day_to_w_m2(self):
        # 1 cal/cm2/day = 4.184e4 / 86400 W/m2 ≈ 0.484259
        assert convert_value(1.0, "cal/cm2/day", "W/m2") == pytest.approx(
            4.184e4 / 86400.0,
        )

    def test_kwh_m2_day_to_w_m2(self):
        assert convert_value(1.0, "kWh/m2/day", "W/m2") == pytest.approx(
            3.6e6 / 86400.0,
        )

    def test_radiation_alias_wm2(self):
        assert convert_value(10.0, "W/m^2", "W/m2") == pytest.approx(10.0)

    def test_radiation_alias_langley(self):
        assert convert_value(1.0, "ly/day", "cal/cm2/day") == pytest.approx(1.0)


# ------------------------------------------------------------------
# Percent / fraction
# ------------------------------------------------------------------


class TestPercentConversion:
    def test_fraction_to_percent(self):
        assert convert_value(0.5, "fraction", "%") == pytest.approx(50.0)

    def test_percent_to_fraction(self):
        assert convert_value(75.0, "%", "fraction") == pytest.approx(0.75)

    def test_ratio_to_percent(self):
        assert convert_value(1.0, "ratio", "%") == pytest.approx(100.0)


# ------------------------------------------------------------------
# Concentration
# ------------------------------------------------------------------


class TestConcentrationConversion:
    def test_g_l_to_mg_l(self):
        assert convert_value(1.0, "g/L", "mg/L") == pytest.approx(1000.0)

    def test_ng_l_to_mg_l(self):
        assert convert_value(1.0e6, "ng/L", "mg/L") == pytest.approx(1.0)

    def test_ug_l_to_g_l(self):
        assert convert_value(1.0e6, "ug/L", "g/L") == pytest.approx(1.0)


# ------------------------------------------------------------------
# CF-convention remapping
# ------------------------------------------------------------------


class TestCFConventionUnits:
    def test_kgm2s_to_mm_s(self):
        # "kg m-2 s-1" is CF precip mass flux, remapped to mm/s
        assert convert_value(1.0, "kg m-2 s-1", "mm/s") == pytest.approx(1.0)

    def test_kgkg_to_fraction(self):
        assert convert_value(0.01, "kg/kg", "fraction") == pytest.approx(0.01)

    def test_kgkg_to_percent(self):
        assert convert_value(0.5, "kg/kg", "%") == pytest.approx(50.0)


# ------------------------------------------------------------------
# Cross-family rejection
# ------------------------------------------------------------------


class TestCrossFamilyRejection:
    def test_length_vs_flow(self):
        with pytest.raises(ValueError, match="Incompatible"):
            convert_value(1.0, "m", "m3/s")

    def test_temperature_vs_percent(self):
        with pytest.raises(ValueError, match="Incompatible"):
            convert_value(1.0, "degC", "%")


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
