"""From a water table to a simulated network, on a toy valley of 24 by 24 cells.

The water table is not solved: it is a subdued copy of the top, which is
enough to show the four levels. Every step after it is a call of the code.
"""

import matplotlib.pyplot as plt
import numpy as np

from hydromodpy.core.depression_filling import fill_depressions_on_graph
from hydromodpy.core.descent import build_descent, descent_graph
from hydromodpy.core.field_routing import (
    accumulate_on_downhill_graph,
    domain_edge_cells,
    seepage_mask,
)
from hydromodpy.core.stream_network import build_simulated_network, specific_seepage_threshold
from hydromodpy.core.topographic_distance import build_downslope_metric, shared_node_adjacency

N, SIZE = 24, 25.0  # cells per side, cell size in m
RECHARGE = 1.0e-8  # m/s, about 315 mm per year
CONDUCTANCE = 1.0e-3  # drain conductance, m2/s


def quad_mesh(n, size):
    corner = (np.arange(n)[:, None] * (n + 1) + np.arange(n)[None, :]).ravel()
    faces = np.column_stack([corner, corner + 1, corner + n + 2, corner + n + 1])
    xx, yy = np.meshgrid(np.arange(n + 1) * size, np.arange(n + 1) * size)
    return np.column_stack([xx.ravel(), yy.ravel(), np.zeros(xx.size)]), faces


vertices, faces = quad_mesh(N, SIZE)
rows, cols = np.divmod(np.arange(N * N), N)
x, y = (cols + 0.5) * SIZE, (rows + 0.5) * SIZE
centres = np.column_stack([x, y])
# A valley that falls to the south, and a tributary from the north-east.
main = np.abs(x - 300.0 - 40.0 * np.sin(y / 120.0))
t = np.clip(((x - 330.0) * 220.0 + (y - 250.0) * 250.0) / (220.0**2 + 250.0**2), 0.0, 1.0)
tributary = np.hypot(x - 330.0 - 220.0 * t, y - 250.0 - 250.0 * t)
relief = 0.03 * np.minimum(main, tributary)
top = 20.0 + 0.02 * y + relief
excess = 0.2 + 0.4 * (1.0 - y / 600.0) + 0.3 * np.sin(y / 40.0) - 0.6 * relief
watertable = top + excess

routable = np.ones(N * N, dtype=bool)
descent = build_descent(top, faces, vertices=vertices, centroids=centres, routable=routable)
mask = seepage_mask(watertable=watertable, topography=top)
release = CONDUCTANCE * np.maximum(watertable - top, 0.0)
accumulated = accumulate_on_downhill_graph(
    descent_graph(descent.receiver, descent.surface), release
)

adjacency = shared_node_adjacency(faces, n_cells=N * N)
filled = fill_depressions_on_graph(top, adjacency, domain_edge_cells(faces, routable)).surface
metric = build_downslope_metric(
    filled, faces, vertices=vertices, centroids=centres, adjacency=adjacency
)
threshold = specific_seepage_threshold(np.full(N * N, SIZE * SIZE), RECHARGE, ratio=0.5)
network = build_simulated_network(release, threshold_m3_s=threshold, metric=metric)
classes = np.where(network.seepage, 2.0, np.where(network.network, 1.0, 0.0))

panels = (
    (mask, "1. seepage mask $m$", "Blues", None),
    (
        np.where(release > 0, release, np.nan),
        "2. release $q^\\mathrm{rel}$ (m$^3$/s)",
        "viridis",
        None,
    ),
    (
        np.where(accumulated > 0, np.log10(np.maximum(accumulated, 1e-12)), np.nan),
        "3. $\\log_{10} F$ on $D$",
        "magma_r",
        None,
    ),
    (classes, "4. sources and the network", "Greens", (0.0, 2.2)),
)
fig, axes = plt.subplots(1, 4, figsize=(8.0, 2.6))
for ax, (values, title, cmap, limits) in zip(axes, panels, strict=True):
    vmin, vmax = limits if limits else (None, None)
    image = ax.imshow(
        values.reshape(N, N),
        origin="lower",
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        extent=(0, N * SIZE, 0, N * SIZE),
    )
    ax.set_title(title, fontsize=8)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(False)
axes[3].text(
    0.5,
    -0.06,
    "dark: source  light: closure",
    transform=axes[3].transAxes,
    ha="center",
    va="top",
    fontsize=7,
)
fig.tight_layout()
