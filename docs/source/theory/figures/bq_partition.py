"""The share of the inflow a cell releases at the surface, by depth of the water table.

Drawn by regularized_partition_surface_rate_from_balance on cells 10 m thick that
receive 1 m/s, so the rate it returns is the factor itself.
"""

from types import SimpleNamespace

import matplotlib.pyplot as plt
import numpy as np

from hydromodpy.physics.flow.flow_runtime_config import DEFAULT_PARTITION_RELEASE_DEPTH_M
from hydromodpy.solver.boussinesq.assembly.surface import (
    regularized_partition_surface_rate_from_balance,
)

depth = np.linspace(0.0, 1.2, 1201)
cells = SimpleNamespace(
    n_cells=depth.size,
    z_bottom_m=np.zeros(depth.size),
    z_top_m=np.full(depth.size, 10.0),
    cell_area_m2=np.ones(depth.size),
)


def factor(depth_scale_m):
    return regularized_partition_surface_rate_from_balance(
        cells,
        10.0 - depth,
        lateral_flux_residual_m3_s=np.zeros(depth.size),
        surface_input_rate_m_s=1.0,
        regularization_radius=depth_scale_m,
    )


default = DEFAULT_PARTITION_RELEASE_DEPTH_M
marks = np.array([0.0, 0.05, 0.1, 0.2, 1.0])
fig, (lin, log) = plt.subplots(1, 2, figsize=(6.4, 3.4))
for ax in (lin, log):
    for depth_scale, style in [(0.02, ":"), (0.1, "-.")]:
        ax.plot(
            depth,
            factor(depth_scale),
            color="C6",
            ls=style,
            lw=1.0,
            label=rf"$\delta$ = {depth_scale:g} m",
        )
    ax.plot(
        depth,
        factor(default),
        color="C1",
        lw=2.0,
        label=rf"$\delta$ = {default:g} m, the default",
    )
    ax.plot(marks, np.interp(marks, depth, factor(default)), "o", color="C1", ms=5)
    ax.set_xlabel(r"depth of the water table $d_i$ (m)")
lin.set_ylabel(r"$s_i / \gamma_i = \exp(-d_i/\delta)$")
for d, f in zip(marks[1:4], np.interp(marks[1:4], depth, factor(default)), strict=True):
    lin.annotate(f"{f:.2g}", (d, f), xytext=(6, 4), textcoords="offset points", fontsize=8)
lin.set_xlim(0.0, 0.3)
lin.set_title("Near the surface", fontsize=10)
log.set_yscale("log")
log.set_ylim(1e-12, 2)
log.set_title("Down to 1.2 m, log scale", fontsize=10)
log.annotate(
    f"{factor(default)[1000]:.1g} at 1 m",
    (depth[1000], factor(default)[1000]),
    xytext=(-40, 12),
    textcoords="offset points",
    fontsize=8,
)
fig.tight_layout(rect=(0, 0.1, 1, 1))
handles, labels = log.get_legend_handles_labels()
fig.legend(handles, labels, loc="lower center", ncol=3, fontsize=8, frameon=False)
