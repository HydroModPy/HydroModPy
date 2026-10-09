"""Two networks on an 8 by 8 grid, and the two downslope distances between them."""

import matplotlib.pyplot as plt
import numpy as np

from hydromodpy.core.depression_filling import fill_depressions_on_graph
from hydromodpy.core.field_routing import domain_edge_cells
from hydromodpy.core.topographic_distance import (
    build_downslope_metric,
    downslope_distance_to_mask,
    shared_node_adjacency,
)

N, SIZE = 8, 10.0
BLUE, ORANGE = "#0072B2", "#D55E00"


def quad_mesh(n, size):
    corner = (np.arange(n)[:, None] * (n + 1) + np.arange(n)[None, :]).ravel()
    faces = np.column_stack([corner, corner + 1, corner + n + 2, corner + n + 1])
    xx, yy = np.meshgrid(np.arange(n + 1) * size, np.arange(n + 1) * size)
    return np.column_stack([xx.ravel(), yy.ravel(), np.zeros(xx.size)]), faces


vertices, faces = quad_mesh(N, SIZE)
rows, cols = np.divmod(np.arange(N * N), N)
centres = np.column_stack([(cols + 0.5) * SIZE, (rows + 0.5) * SIZE])
# A valley along column 3 that falls to the south (row 0), the outlet at its foot.
top = 10.0 + 0.5 * rows + 0.8 * np.abs(cols - 3) + 0.05 * cols
top[(rows == 0) & (cols == 3)] = 9.0

active = np.ones(N * N, dtype=bool)
adjacency = shared_node_adjacency(faces, n_cells=N * N)
filled = fill_depressions_on_graph(top, adjacency, domain_edge_cells(faces, active)).surface
metric = build_downslope_metric(
    filled, faces, vertices=vertices, centroids=centres, adjacency=adjacency
)

cell = rows * N + cols
mapped = (cols == 3) & (rows <= 6)  # O: the map reaches row 6
simulated = ((cols == 3) & (rows <= 3)) | ((cols == 6) & (rows >= 4) & (rows <= 5))  # S
d_to_mapped = downslope_distance_to_mask(metric, mapped)
d_to_simulated = downslope_distance_to_mask(metric, simulated)

fig, axes = plt.subplots(1, 2, figsize=(6.4, 3.4))
for ax, support, distance, colour, title in (
    (
        axes[0],
        simulated,
        d_to_mapped,
        ORANGE,
        "$D_{so}$: from $\\mathcal{S}$ to $\\mathcal{O}$",
    ),
    (
        axes[1],
        mapped,
        d_to_simulated,
        BLUE,
        "$D_{os}$: from $\\mathcal{O}$ to $\\mathcal{S}$",
    ),
):
    ax.imshow(
        filled.reshape(N, N),
        origin="lower",
        cmap="Greys",
        alpha=0.35,
        extent=(0, N * SIZE, 0, N * SIZE),
    )
    for c in range(N * N):
        r = metric.graph.downstream[c]
        if r >= 0:
            dx, dy = centres[r] - centres[c]
            ax.annotate(
                "",
                xy=centres[c] + 0.45 * np.array([dx, dy]),
                xytext=centres[c],
                arrowprops={"arrowstyle": "-|>", "color": "0.55", "lw": 0.6},
            )
    ax.scatter(*centres[mapped].T, marker="s", s=70, facecolor="none", edgecolor=BLUE, lw=1.6)
    ax.scatter(*centres[simulated].T, marker="o", s=40, color=ORANGE, alpha=0.8)
    for c in np.flatnonzero(support):
        ax.text(
            centres[c, 0] + 2.2,
            centres[c, 1] + 2.4,
            f"{distance[c]:.0f}",
            fontsize=7,
            color=colour,
            ha="left",
            va="bottom",
        )
    mean = float(np.mean(distance[support]))
    ax.set_title(f"{title}\nmean {mean:.1f} m", fontsize=9)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(False)
    ax.set_aspect("equal")
axes[0].text(
    0.0,
    -0.04,
    "squares: mapped $\\mathcal{O}$   dots: simulated $\\mathcal{S}$",
    transform=axes[0].transAxes,
    fontsize=7,
    va="top",
)
fig.tight_layout()
