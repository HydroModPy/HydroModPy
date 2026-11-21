"""ETP formulas from the air temperature (mm/day, degC, degrees of latitude).

The radiation and the day length are checked on the worked examples of FAO-56,
the formulas on their own closed forms, and the date reading on leap years.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.model.soil.etp import (
    ETP_FORMULAS,
    day_length_fao56,
    day_length_forsythe,
    day_of_year,
    extraterrestrial_radiation,
    hamon,
    oudin,
)

SEPT_3 = np.array(["2021-09-03"], dtype="datetime64[D]")
YEAR = np.arange(np.datetime64("2021-01-01"), np.datetime64("2022-01-01"))


def test_extraterrestrial_radiation_matches_fao56_example_8():
    # 20 degS, 3 September: Ra = 32.2 MJ m-2 day-1.
    assert extraterrestrial_radiation(np.array([-20.0]), SEPT_3)[0, 0] == pytest.approx(
        32.2, abs=0.05
    )


def test_day_length_matches_fao56_example_9():
    # 20 degS, 3 September: N = 11.7 hours.
    assert day_length_fao56(np.array([-20.0]), SEPT_3)[0, 0] == pytest.approx(11.7, abs=0.05)


def test_forsythe_day_length_is_half_a_day_at_the_equinox_and_long_at_the_solstice():
    equinox = np.array(["2021-03-20"], dtype="datetime64[D]")
    solstice = np.array(["2021-06-21"], dtype="datetime64[D]")
    assert day_length_forsythe(np.array([48.0]), equinox)[0, 0] == pytest.approx(12.0, abs=0.15)
    assert day_length_forsythe(np.array([48.0]), solstice)[0, 0] == pytest.approx(15.8, abs=0.1)


def test_the_day_of_the_year_does_not_drift_over_leap_years():
    days = np.array(["2020-12-31", "2021-01-01", "2024-03-01", "2025-03-01"], dtype="datetime64[D]")
    np.testing.assert_array_equal(day_of_year(days), [366, 1, 61, 60])


def test_oudin_is_its_closed_form_and_zero_below_minus_five():
    temperature = np.array([[-6.0, -5.0, 15.0]])
    latitude = np.array([48.0, 48.0, 48.0])
    re = extraterrestrial_radiation(latitude, SEPT_3)
    expected = re[0] / (2.45 * 1000.0) * (temperature[0] + 5.0) / 100.0 * 1000.0
    expected[:2] = 0.0
    np.testing.assert_allclose(oudin(temperature, latitude, SEPT_3)[0], expected)


def test_hamon_is_the_espere_form():
    temperature = np.array([[12.0]])
    day_length = day_length_forsythe(np.array([48.0]), SEPT_3)[0, 0]
    e_sat = 0.611 * np.exp(17.3 * 12.0 / (12.0 + 237.3))
    assert hamon(temperature, np.array([48.0]), SEPT_3)[0, 0] == pytest.approx(
        29.8 * day_length * e_sat / (12.0 + 273.2)
    )


@pytest.mark.parametrize("name", list(ETP_FORMULAS))
def test_a_temperate_year_gives_a_temperate_etp(name):
    # A Rennes-like year, 11 degC mean, 7 degC of amplitude: 500 to 900 mm/year.
    temperature = (11.0 + 7.0 * np.sin(2 * np.pi * (np.arange(365) - 110) / 365))[:, None]
    etp = ETP_FORMULAS[name].formula(temperature, np.array([48.1]), YEAR)
    assert np.all(etp >= 0.0)
    assert 500.0 < etp.sum() < 900.0
    assert etp[180, 0] > 4 * etp[0, 0]
