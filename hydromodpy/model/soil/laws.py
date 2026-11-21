"""The storage laws of the soil reservoir, one function per method, numpy only.

A law takes one day of one set of columns. It reads the soil water at the start
of the day, the water that enters the soil that day, the evaporative demand
``kc x ETP`` and the capacity ``RU``, all in mm. It returns three arrays: the
actual evapotranspiration, the soil water at the end of the day, and the excess
that leaves the soil. The three always close the balance

    soil + inflow = etr + soil_end + excess

so the shell around the law (sealed share, curve number, bypass, transit, snow)
is the same for every method. A column with ``RU = 0`` has no store: every law
evaporates what it can of the inflow and passes the rest on, the same day.

The methods and where their equations come from:

- ``fao56``: the soil evaporates at the full rate down to ``alpha x RU``, then
  linearly less with the stored water (Allen et al. 1998, FAO-56 eq. 84; LP of
  HBV). The rain reaches the soil before it evaporates. This is the default.
- ``thornthwaite``: no resistance of the soil, the full demand is met while
  water is left (Thornthwaite 1948, as coded by ESPERE, BRGM RP-69538-FR).
- ``dingman``: on a dry day the store empties as an exponential of the deficit
  over RU (Dingman 2008, as coded by ESPERE).
- ``edijatno_michel``: the quadratic production store of Edijatno and Michel
  (1989), the one GR4J uses, without the GR4J percolation. Part of the net rain
  leaves before the store is full. ESPERE tests the rainy branch on ETP without
  kc; this law tests it on the demand, which closes the balance for any kc.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np


def fao56(
    soil: np.ndarray, inflow: np.ndarray, demand: np.ndarray, ru: np.ndarray, alpha: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Full rate down to ``alpha x RU``, then a straight line to zero."""
    wet_soil = soil + inflow
    has_capacity = ru > 0
    ratio = np.ones_like(wet_soil)
    ratio[has_capacity] = np.minimum(1.0, wet_soil[has_capacity] / (alpha * ru[has_capacity]))
    etr = np.minimum(wet_soil, demand * ratio)
    wet_soil = wet_soil - etr
    excess = np.maximum(0.0, wet_soil - ru)
    return etr, wet_soil - excess, excess


def thornthwaite(
    soil: np.ndarray, inflow: np.ndarray, demand: np.ndarray, ru: np.ndarray, alpha: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The full demand while water is left, then the store overflows above RU."""
    del alpha
    wet_soil = soil + inflow
    etr = np.minimum(wet_soil, demand)
    wet_soil = wet_soil - etr
    excess = np.maximum(0.0, wet_soil - ru)
    return etr, wet_soil - excess, excess


def dingman(
    soil: np.ndarray, inflow: np.ndarray, demand: np.ndarray, ru: np.ndarray, alpha: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Wet day: full demand and overflow above RU. Dry day: ``soil x exp(-deficit / RU)``."""
    del alpha
    wet_day = inflow >= demand
    safe_ru = np.where(ru > 0, ru, 1.0)
    dry_soil = np.where(ru > 0, soil * np.exp(np.minimum(inflow - demand, 0.0) / safe_ru), 0.0)
    filled = soil + inflow - demand
    wet_soil_end = np.minimum(filled, ru)
    soil_end = np.where(wet_day, wet_soil_end, dry_soil)
    excess = np.where(wet_day, filled - wet_soil_end, 0.0)
    etr = soil + inflow - soil_end - excess
    return etr, soil_end, excess


def edijatno_michel(
    soil: np.ndarray, inflow: np.ndarray, demand: np.ndarray, ru: np.ndarray, alpha: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """GR production store: ``tanh`` filling on net rain, ``tanh`` emptying on net demand."""
    del alpha
    has_capacity = ru > 0
    safe_ru = np.where(has_capacity, ru, 1.0)
    level = soil / safe_ru

    net_rain = np.maximum(inflow - demand, 0.0)
    t_rain = np.tanh(net_rain / safe_ru)
    filled = safe_ru * (level + t_rain) / (1.0 + level * t_rain)

    net_demand = np.maximum(demand - inflow, 0.0)
    t_dry = np.tanh(net_demand / safe_ru)
    emptied = safe_ru * level * (1.0 - t_dry) / (1.0 + (1.0 - level) * t_dry)

    wet_day = inflow >= demand
    soil_end = np.where(has_capacity, np.where(wet_day, filled, emptied), 0.0)
    excess = np.where(
        has_capacity,
        np.where(wet_day, net_rain - (soil_end - soil), 0.0),
        np.maximum(inflow - demand, 0.0),
    )
    etr = soil + inflow - soil_end - excess
    return etr, soil_end, excess


SoilLaw = Callable[
    [np.ndarray, np.ndarray, np.ndarray, np.ndarray, float],
    tuple[np.ndarray, np.ndarray, np.ndarray],
]


@dataclass(frozen=True, slots=True)
class SoilMethod:
    """One method of the soil reservoir: its law and what a reader needs to know of it."""

    law: SoilLaw
    label: str
    reference: str
    reads_alpha: bool


SOIL_METHODS: dict[str, SoilMethod] = {
    "fao56": SoilMethod(
        law=fao56,
        label="linear water stress below alpha x RU",
        reference="Allen et al. (1998), FAO-56",
        reads_alpha=True,
    ),
    "thornthwaite": SoilMethod(
        law=thornthwaite,
        label="full demand while water is left",
        reference="Thornthwaite (1948)",
        reads_alpha=False,
    ),
    "dingman": SoilMethod(
        law=dingman,
        label="exponential emptying on dry days",
        reference="Dingman (2008)",
        reads_alpha=False,
    ),
    "edijatno_michel": SoilMethod(
        law=edijatno_michel,
        label="quadratic production store of GR4J, no percolation",
        reference="Edijatno and Michel (1989)",
        reads_alpha=False,
    ),
}
"""The soil methods a ``[flow.sinks_sources.recharge.soil]`` table can name."""
