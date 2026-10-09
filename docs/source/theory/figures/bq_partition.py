"""The share of the inflow a cell releases at the surface, by saturation.

Drawn by regularized_partition_surface_rate_from_balance on cells of 1 m
thickness that receive 1 m/s, so the rate it returns is the factor itself.
"""

from types import SimpleNamespace

import matplotlib.pyplot as plt
import numpy as np

from hydromodpy.solver.boussinesq import boussinesq
from hydromodpy.solver.boussinesq.assembly.surface import (
    regularized_partition_surface_rate_from_balance,
)

sigma = np.linspace(0.0, 1.0, 501)
cells = SimpleNamespace(
    n_cells=sigma.size,
    z_bottom_m=np.zeros(sigma.size),
    z_top_m=np.ones(sigma.size),
    cell_area_m2=np.ones(sigma.size),
)


def factor(radius):
    return regularized_partition_surface_rate_from_balance(
        cells,
        sigma,  # with a 1 m cell on a bottom at 0, the head is the saturation
        lateral_flux_residual_m3_s=np.zeros(sigma.size),
        surface_input_rate_m_s=1.0,
        regularization_radius=radius,
    )


default = boussinesq._DEFAULT_SATURATION_EXCESS_REGULARIZATION
marks = np.array([0.5, 0.8, 0.9, 0.95, 1.0])
fig, (lin, log) = plt.subplots(1, 2, figsize=(6.4, 3.4))
for ax in (lin, log):
    for radius, style in [(0.02, ":"), (0.1, "-.")]:
        ax.plot(
            sigma,
            factor(radius),
            color="C6",
            ls=style,
            lw=1.0,
            label=rf"$\varepsilon_r$ = {radius:g}",
        )
    ax.plot(
        sigma,
        factor(default),
        color="C1",
        lw=2.0,
        label=rf"$\varepsilon_r$ = {default:g}, the code",
    )
    on_curve = np.interp(marks, sigma, factor(default))
    ax.plot(marks, on_curve, "o", color="C1", ms=5)
    ax.set_xlabel(r"saturation $\sigma_i$")
lin.set_ylabel(r"$s_i / \gamma_i = \exp(-(1 - \sigma_i)/\varepsilon_r)$")
for s, f in zip(marks[1:4], np.interp(marks[1:4], sigma, factor(default)), strict=True):
    lin.annotate(f"{f:.2g}", (s, f), xytext=(6, -10), textcoords="offset points", fontsize=8)
lin.set_xlim(0.6, 1.0)
lin.set_title("Near a full cell", fontsize=10)
log.set_yscale("log")
log.set_ylim(1e-9, 2)
log.set_title("The whole range, log scale", fontsize=10)
log.annotate(
    f"{factor(default)[250]:.2g} at half full",
    (sigma[250], factor(default)[250]),
    xytext=(-10, 12),
    textcoords="offset points",
    fontsize=8,
)
fig.tight_layout(rect=(0, 0.1, 1, 1))
handles, labels = log.get_legend_handles_labels()
fig.legend(handles, labels, loc="lower center", ncol=3, fontsize=8, frameon=False)
