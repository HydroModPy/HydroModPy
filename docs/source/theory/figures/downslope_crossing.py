"""The two mean distances against the calibrated ratio, on a toy catchment.

No solver runs here. A cell seeps when the recharge drained through it exceeds
what a saturated thickness B can carry down its slope, N A_d > K B s w: the
shape of a drain model at steady state, with K/N as the one parameter. The
mapped network is a drained-area threshold. Every distance is a call of the
code the criterion uses.
"""

import matplotlib.pyplot as plt
import numpy as np
from scipy.ndimage import gaussian_filter

from hydromodpy.core.depression_filling import fill_depressions_on_graph
from hydromodpy.core.field_routing import accumulate_on_downhill_graph, domain_edge_cells
from hydromodpy.core.stream_network import downstream_closure
from hydromodpy.core.topographic_distance import (
    build_downslope_metric,
    downslope_distance_to_mask,
    longest_descent_length,
    mean_downslope_distance,
    shared_node_adjacency,
)

N, SIZE, THICKNESS = 60, 20.0, 30.0  # cells per side, cell size (m), B (m)


def quad_mesh(n, size):
    corner = (np.arange(n)[:, None] * (n + 1) + np.arange(n)[None, :]).ravel()
    faces = np.column_stack([corner, corner + 1, corner + n + 2, corner + n + 1])
    xx, yy = np.meshgrid(np.arange(n + 1) * size, np.arange(n + 1) * size)
    return np.column_stack([xx.ravel(), yy.ravel(), np.zeros(xx.size)]), faces


vertices, faces = quad_mesh(N, SIZE)
rows, cols = np.divmod(np.arange(N * N), N)
centres = np.column_stack([(cols + 0.5) * SIZE, (rows + 0.5) * SIZE])
noise = gaussian_filter(np.random.default_rng(7).normal(size=(N, N)), 3.0).ravel()
top = 50.0 + 0.03 * centres[:, 1] + 0.02 * np.abs(centres[:, 0] - 600.0) + 40.0 * noise

active = np.ones(N * N, dtype=bool)
adjacency = shared_node_adjacency(faces, n_cells=N * N)
filled = fill_depressions_on_graph(top, adjacency, domain_edge_cells(faces, active)).surface
metric = build_downslope_metric(
    filled, faces, vertices=vertices, centroids=centres, adjacency=adjacency
)
area = np.full(N * N, SIZE * SIZE)
drained = accumulate_on_downhill_graph(metric.graph, area)
receiver = metric.graph.downstream
slope = np.full(N * N, 1.0e-3)
has = receiver >= 0
slope[has] = np.maximum((filled[has] - filled[receiver[has]]) / metric.edge_length[has], 1.0e-3)

outlet = np.zeros(N * N, dtype=bool)
outlet[int(np.nanargmax(np.where(np.isfinite(drained), drained, -1.0)))] = True
catchment = np.isfinite(downslope_distance_to_mask(metric, outlet))
cap = longest_descent_length(metric, outlet, within=catchment)
mapped = (drained >= 0.03e6) & catchment  # O: cells draining at least 0.03 km2
to_mapped_target = mapped | outlet

ratios = np.logspace(3.0, 5.2, 34)  # K / N
d_so, d_os = [], []
for ratio in ratios:
    sources = drained > ratio * THICKNESS * slope * SIZE
    simulated = downstream_closure(metric, sources) & catchment
    to_mapped = downslope_distance_to_mask(metric, to_mapped_target)
    to_simulated = downslope_distance_to_mask(metric, simulated)
    so = mean_downslope_distance(to_mapped, simulated, saturation_cap_m=cap)
    os_ = mean_downslope_distance(to_simulated, mapped, saturation_cap_m=cap)
    d_so.append(so.mean_m if simulated.any() else np.nan)
    d_os.append(os_.mean_m)
d_so, d_os = np.array(d_so), np.array(d_os)
gap = d_so - d_os
cross = np.flatnonzero(np.nan_to_num(gap[:-1], nan=-1.0) * gap[1:] <= 0.0)

fig, ax = plt.subplots(figsize=(6.4, 3.6))
ax.plot(ratios, d_so, marker="o", ms=3, label="$D_{so}$, simulated to mapped")
ax.plot(ratios, d_os, marker="s", ms=3, label="$D_{os}$, mapped to simulated")
ax.plot(ratios, 0.5 * (d_so + d_os), color="0.5", lw=1.0, ls=":", label="$D_{optim}$")
if cross.size:
    ax.axvspan(ratios[cross[0]], ratios[cross[0] + 1], color="0.85", zorder=0)
    ax.text(ratios[cross[0] + 1] * 1.05, 0.5, "$J = 0$", fontsize=9, va="bottom")
ax.set_xscale("log")
ax.set_xlabel("calibrated ratio $K/\\bar N$ (-)")
ax.set_ylabel("mean downslope distance (m)")
ax.text(ratios[0], 36, "too much stream", fontsize=8, color="0.3")
ax.text(ratios[-1], 2.0, "too little stream", fontsize=8, color="0.3", ha="right")
ax.legend(fontsize=8, loc="upper left", bbox_to_anchor=(0.3, 1.0))
fig.tight_layout()
