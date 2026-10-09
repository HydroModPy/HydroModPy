"""Mean annual recharge and evapotranspiration against the soil capacity RU.

The kernel runs on a synthetic six-year climate of a temperate oceanic site:
904 mm of rain per year on about one day in two, more in winter, and a
reference evapotranspiration of 698 mm per year that peaks in July. The other
parameters keep their defaults (alpha 0.6, kc 1, no sealed share, no bypass,
no transit time, no curve number).
"""

import matplotlib.pyplot as plt
import numpy as np

from hydromodpy.physics.hydrology.soil_reservoir.kernel import (
    SoilParameters,
    run_soil_balance,
    spinup_state,
)

YEARS, RAIN, ETP = 6, 904.0, 698.0  # mm per year
days = np.arange(YEARS * 365)
season = np.cos(2.0 * np.pi * (days - 15) / 365.0)  # +1 in mid-January
rng = np.random.default_rng(2015)
wet = rng.random(days.size) < 0.5 + 0.12 * season
depth = rng.exponential(1.0, days.size) * (1.0 + 0.35 * season)
rain = np.where(wet, depth, 0.0)
rain *= RAIN * YEARS / rain.sum()
etp = ETP / 365.0 * (1.0 - 0.8 * season)

ru = np.arange(0.0, 301.0, 10.0)
params = SoilParameters(
    ru_mm=ru,
    alpha=0.6,
    kc=1.0,
    impervious_fraction=0.0,
    bypass_fraction=0.0,
    transit_time_days=0.0,
)
forcing_p = np.repeat(rain[:, None], ru.size, axis=1)
forcing_e = np.repeat(etp[:, None], ru.size, axis=1)
spinup = spinup_state(forcing_p, forcing_e, params)
fluxes = run_soil_balance(forcing_p, forcing_e, params, spinup.state)
recharge = fluxes.recharge.sum(axis=0) / YEARS
etr = fluxes.etr.sum(axis=0) / YEARS

fig, ax = plt.subplots(figsize=(6.4, 3.4))
ax.plot(ru, recharge, label="recharge $N$")
ax.plot(ru, etr, label="evapotranspiration ETR")
ax.axhline(RAIN, color="0.5", lw=0.8, ls="--")
ax.text(300, RAIN - 15, "rain", ha="right", va="top", fontsize=8, color="0.4")
for value in (50.0, 250.0):
    i = int(np.argmin(np.abs(ru - value)))
    ax.plot(ru[i], recharge[i], "o", color="#0072B2")
    ax.annotate(
        f"{recharge[i]:.0f} mm/yr",
        (ru[i], recharge[i]),
        xytext=(4, 6),
        textcoords="offset points",
        fontsize=8,
    )
ax.set_xlabel("soil capacity RU (mm)")
ax.set_ylabel("mean over the run (mm/year)")
ax.set_xlim(0.0, 300.0)
ax.set_ylim(0.0, 1000.0)
ax.legend(fontsize=8, loc="center right")
fig.tight_layout()
