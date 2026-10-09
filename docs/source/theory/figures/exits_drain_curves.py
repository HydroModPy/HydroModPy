"""Discharge of one drain cell against its head, for the four rows of the worked cell."""

import matplotlib.pyplot as plt
import numpy as np

from hydromodpy.solver.modflow_common.drain_conductance import (
    drain_discharge_band,
    hk_fallback_drain_conductance,
)

AREA = 25.0 * 25.0  # m2
K = 1.0e-7  # m/s
RECHARGE = 0.439 / (365.25 * 86400.0)  # 439 mm per year, in m/s
FLOOR = 1.0e-12  # m2/s, the default floor
CASES = (  # bed thickness b_d (m), band depth delta (m)
    (30.0, 0.0),
    (1.0, 0.0),
    (0.1, 0.0),
    (1.0, 0.5),
)

head = np.linspace(-0.40, 0.25, 400)  # head minus model top, m
fig, ax = plt.subplots(figsize=(6.4, 3.6))
for bed, band in CASES:
    conductance = hk_fallback_drain_conductance(
        hk=K, cell_area=AREA, bed_thickness=bed, floor_m2_s=FLOOR
    )
    elevation, conductance = drain_discharge_band(
        top=0.0, conductance=conductance, bed_thickness=bed, band_depth=band
    )
    discharge = conductance * np.maximum(head - elevation, 0.0)
    label = f"$b_d$ = {bed:g} m" + (f", band $\\delta$ = {band:g} m" if band else "")
    ax.plot(head, discharge / (RECHARGE * AREA), label=label)

ax.axhline(1.0, color="0.3", lw=0.8, ls="--")
ax.text(-0.39, 1.05, "the cell passes its own recharge", fontsize=8, va="bottom")
ax.axvline(0.0, color="0.3", lw=0.8)
ax.text(0.005, 2.85, "model top", fontsize=8, va="top")
ax.set_xlim(head[0], head[-1])
ax.set_ylim(0.0, 3.0)
ax.set_xlabel("head minus model top, $h - z_\\mathrm{top}$ (m)")
ax.set_ylabel("drain discharge / recharge of the cell")
ax.legend(fontsize=8, loc="upper left", bbox_to_anchor=(0.0, 0.9))
fig.tight_layout()
