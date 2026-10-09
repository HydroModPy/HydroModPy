"""The Fischer-Burmeister function of the surface threshold, and its zero set."""

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import TwoSlopeNorm

from hydromodpy.solver.boussinesq.runtimes.petsc_mixed_common import (
    _fischer_burmeister_residual_and_derivatives,
)

# Unit scales, so the two arguments are the scaled variables of the page.
u, v = np.meshgrid(np.linspace(-1.0, 2.0, 301), np.linspace(-1.0, 2.0, 301))
phi, _, _ = _fischer_burmeister_residual_and_derivatives(u, v, head_scale_m=1.0, rate_scale_m_s=1.0)

fig, ax = plt.subplots(figsize=(5.2, 4.2))
image = ax.contourf(u, v, phi, levels=21, cmap="RdBu_r", norm=TwoSlopeNorm(0.0))
ax.contour(u, v, phi, levels=[-1.0, -0.5, 0.5, 1.0, 2.0], colors="C6", linewidths=0.4)
ax.plot([0, 0], [0, 2], color="C6", lw=3.0)
ax.plot([0, 2], [0, 0], color="C6", lw=3.0)
box = {"boxstyle": "round", "fc": "white", "ec": "none", "alpha": 0.9}
arrow = {"arrowstyle": "->", "color": "C6"}
ax.annotate(
    "head below the surface,\nnothing released",
    (0.0, 1.2),
    xytext=(0.35, 1.55),
    fontsize=9,
    bbox=box,
    arrowprops=arrow,
)
ax.annotate(
    "head at the surface,\nwater released",
    (1.2, 0.0),
    xytext=(0.6, -0.7),
    fontsize=9,
    bbox=box,
    arrowprops=arrow,
)
ax.set_xlabel(r"scaled release $q^\mathrm{ex}_i / q_s$")
ax.set_ylabel(r"scaled gap $(z_{\mathrm{top},i} - h_i) / h_s$")
ax.set_aspect("equal")
ax.grid(False)
bar = fig.colorbar(image, ax=ax, shrink=0.85)
bar.set_label(r"$\phi_\mathrm{FB}$")
ax.set_title(r"$\phi_\mathrm{FB} = 0$ on the thick line only", fontsize=10)
fig.tight_layout()
