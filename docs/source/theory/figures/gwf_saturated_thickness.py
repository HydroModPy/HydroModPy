"""Saturated thickness and storage of one cell against its head."""

from types import SimpleNamespace

import matplotlib.pyplot as plt
import numpy as np

from hydromodpy.solver.boussinesq.assembly.fluxes import saturated_thickness_from_head

# The cell of the worked example of the page.
Z_BOT, Z_TOP, SY, SS = 70.0, 100.0, 0.05, 1e-5
cell = SimpleNamespace(z_top_m=np.array([Z_TOP]), z_bottom_m=np.array([Z_BOT]))

h = np.linspace(60.0, 110.0, 1001)
B = np.array([saturated_thickness_from_head(cell, [value])[0] for value in h])
chi = ((h > Z_BOT) & (h < Z_TOP)).astype(float)
storage = SS * B + SY * chi

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(6.4, 3.4))
for ax in (ax1, ax2):
    ax.axvspan(Z_BOT, Z_TOP, color="C5", alpha=0.2, lw=0)
    ax.set_xlabel(r"head $h$ (m)")
ax1.plot(h, B, color="C0", lw=1.8)
ax1.set_ylabel(r"$B(h)$ (m)")
ax1.set_title("Saturated thickness", fontsize=10)
ax1.annotate(r"$H = 30$ m", (106, 30), xytext=(0, -16), textcoords="offset points", ha="center")
ax1.set_xticks(
    [60, Z_BOT, 85, Z_TOP, 110], ["60", r"$z_\mathrm{bot}$", "85", r"$z_\mathrm{top}$", "110"]
)

ax2.semilogy(h, np.where(storage > 0, storage, np.nan), color="C1", lw=1.8)
ax2.set_ylim(1e-5, 0.2)
ax2.set_ylabel(r"$S_s B + S_y \chi$ (-)")
ax2.set_title("Storage per unit of head", fontsize=10)
ax2.annotate(
    r"$S_y$ releases the pores", (85, 0.05), xytext=(0, 8), textcoords="offset points", ha="center"
)
ax2.annotate(
    r"$S_s B$ only", (105, SS * 30), xytext=(0, 8), textcoords="offset points", ha="center"
)
ax2.text(65, 2e-5, "zero\nbelow\nthe bottom", ha="center", va="bottom", fontsize=8)
ax2.set_xticks(
    [60, Z_BOT, 85, Z_TOP, 110], ["60", r"$z_\mathrm{bot}$", "85", r"$z_\mathrm{top}$", "110"]
)
fig.tight_layout()
