"""Potential evapotranspiration from the daily air temperature, numpy only.

A project that has no ETP product, or wants another one, can compute it from
``[data.temperature]``. Each formula takes the daily mean temperature (degC)
of each column, its latitude (degrees) and the days, and returns the ETP in
mm/day, never negative.

- ``oudin``: ``ETP = Re / (lambda rho) x (T + 5) / 100`` where ``T + 5 > 0``, else 0
  (Oudin et al. 2005). ``Re`` is the extraterrestrial radiation of FAO-56
  (Allen et al. 1998, eq. 21 to 25). It is the formula GR4J is usually run with.
- ``hamon``: ``ETP = 29.8 D e_sat(T) / (T + 273.2)`` with ``D`` the day length in
  hours and ``e_sat`` in kPa (Hamon 1963), as ESPERE codes it with the day length
  of Forsythe et al. (1995).

The day of the year is read from the date, so a leap year does not shift the
seasons (ESPERE counts ``i mod 365`` and drifts one day every four years).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

LATENT_HEAT_MJ_PER_KG = 2.45  # lambda of FAO-56 at about 20 degC
WATER_DENSITY_KG_PER_M3 = 1000.0
SOLAR_CONSTANT_MJ_PER_M2_MIN = 0.0820  # Gsc of FAO-56


def day_of_year(days: np.ndarray) -> np.ndarray:
    """Day of the year of each date, 1 on January 1st, shape (T,)."""
    days = np.asarray(days, dtype="datetime64[D]")
    return (days - days.astype("datetime64[Y]").astype("datetime64[D]")).astype(np.int64) + 1


def extraterrestrial_radiation(latitude_deg: np.ndarray, days: np.ndarray) -> np.ndarray:
    """Daily extraterrestrial radiation Re, MJ m-2 day-1, shape (T, N) (FAO-56 eq. 21)."""
    j = day_of_year(days)[:, np.newaxis].astype(np.float64)
    phi = np.radians(np.asarray(latitude_deg, dtype=np.float64))[np.newaxis, :]
    inverse_distance = 1.0 + 0.033 * np.cos(2.0 * np.pi * j / 365.0)
    declination = 0.409 * np.sin(2.0 * np.pi * j / 365.0 - 1.39)
    sunset_angle = np.arccos(np.clip(-np.tan(phi) * np.tan(declination), -1.0, 1.0))
    return (
        24.0
        * 60.0
        / np.pi
        * SOLAR_CONSTANT_MJ_PER_M2_MIN
        * inverse_distance
        * (
            sunset_angle * np.sin(phi) * np.sin(declination)
            + np.cos(phi) * np.cos(declination) * np.sin(sunset_angle)
        )
    )


def day_length_fao56(latitude_deg: np.ndarray, days: np.ndarray) -> np.ndarray:
    """Daylight hours N, shape (T, N) (FAO-56 eq. 34)."""
    j = day_of_year(days)[:, np.newaxis].astype(np.float64)
    phi = np.radians(np.asarray(latitude_deg, dtype=np.float64))[np.newaxis, :]
    declination = 0.409 * np.sin(2.0 * np.pi * j / 365.0 - 1.39)
    return 24.0 / np.pi * np.arccos(np.clip(-np.tan(phi) * np.tan(declination), -1.0, 1.0))


def day_length_forsythe(latitude_deg: np.ndarray, days: np.ndarray) -> np.ndarray:
    """Day length in hours, shape (T, N), by the CBM model of Forsythe et al. (1995)."""
    j = day_of_year(days)[:, np.newaxis].astype(np.float64)
    phi = np.radians(np.asarray(latitude_deg, dtype=np.float64))[np.newaxis, :]
    revolution = 0.2163108 + 2.0 * np.arctan(0.9671396 * np.tan(0.00860 * (j - 186.0)))
    declination = np.arcsin(0.39795 * np.cos(revolution))
    return 24.0 / np.pi * np.arccos(np.clip(-np.tan(phi) * np.tan(declination), -1.0, 1.0))


def oudin(temperature: np.ndarray, latitude_deg: np.ndarray, days: np.ndarray) -> np.ndarray:
    """Oudin et al. (2005), mm/day."""
    re = extraterrestrial_radiation(latitude_deg, days)
    metres = re / (LATENT_HEAT_MJ_PER_KG * WATER_DENSITY_KG_PER_M3) * (temperature + 5.0) / 100.0
    return np.where(temperature + 5.0 > 0.0, 1000.0 * metres, 0.0)


def hamon(temperature: np.ndarray, latitude_deg: np.ndarray, days: np.ndarray) -> np.ndarray:
    """Hamon (1963) as ESPERE codes it, mm/day."""
    day_length = day_length_forsythe(latitude_deg, days)
    e_sat_kpa = 0.611 * np.exp(17.3 * temperature / (temperature + 237.3))
    return np.maximum(29.8 * day_length * e_sat_kpa / (temperature + 273.2), 0.0)


EtpFormula = Callable[[np.ndarray, np.ndarray, np.ndarray], np.ndarray]


@dataclass(frozen=True, slots=True)
class EtpMethod:
    """One ETP formula and what a reader needs to know of it."""

    formula: EtpFormula
    label: str
    reference: str


ETP_FORMULAS: dict[str, EtpMethod] = {
    "oudin": EtpMethod(
        formula=oudin,
        label="temperature and extraterrestrial radiation",
        reference="Oudin et al. (2005)",
    ),
    "hamon": EtpMethod(
        formula=hamon,
        label="temperature and day length",
        reference="Hamon (1963)",
    ),
}
"""The formulas ``[data.etp] formula`` can name."""
