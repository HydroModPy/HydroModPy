"""The heads rule on a toy valley: a mapped line drawn from where it starts."""

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Circle

from hydromodpy.core.depression_filling import fill_depressions_on_graph
from hydromodpy.core.field_routing import domain_edge_cells
from hydromodpy.core.stream_heads import HeadCandidates, HeadsSettings, trace_from_heads
from hydromodpy.core.topographic_distance import build_downslope_metric, shared_node_adjacency

N, SIZE = 20, 25.0
BLUE, ORANGE, GREEN = "#0072B2", "#D55E00", "#009E73"


def quad_mesh(n, size):
    corner = (np.arange(n)[:, None] * (n + 1) + np.arange(n)[None, :]).ravel()
    faces = np.column_stack([corner, corner + 1, corner + n + 2, corner + n + 1])
    xx, yy = np.meshgrid(np.arange(n + 1) * size, np.arange(n + 1) * size)
    return np.column_stack([xx.ravel(), yy.ravel(), np.zeros(xx.size)]), faces


vertices, faces = quad_mesh(N, SIZE)
rows, cols = np.divmod(np.arange(N * N), N)
x, y = (cols + 0.5) * SIZE, (rows + 0.5) * SIZE
centres = np.column_stack([x, y])
# A talweg at x = 250 m falling south, and a tributary from the north-east.
t = np.clip(((x - 250.0) * 200.0 + (y - 200.0) * 250.0) / (200.0**2 + 250.0**2), 0.0, 1.0)
tributary = np.hypot(x - 250.0 - 200.0 * t, y - 200.0 - 250.0 * t)
top = 30.0 + 0.03 * y + 0.04 * np.minimum(np.abs(x - 250.0), tributary)

active = np.ones(N * N, dtype=bool)
adjacency = shared_node_adjacency(faces, n_cells=N * N)
filled = fill_depressions_on_graph(top, adjacency, domain_edge_cells(faces, active)).surface
metric = build_downslope_metric(
    filled, faces, vertices=vertices, centroids=centres, adjacency=adjacency
)

# The mapped lines run beside the talweg, as a ditched stream does.
main_line = np.array([[268.0, 470.0], [283.0, 380.0], [262.0, 300.0], [279.0, 210.0]])
lower_line = np.array([[279.0, 210.0], [266.0, 120.0], [281.0, 15.0]])
side_line = np.array([[438.0, 440.0], [370.0, 340.0], [279.0, 210.0]])
confluence = lower_line[0]
candidates = HeadCandidates(
    head_xy=np.array([main_line[0], side_line[0], lower_line[-1]]),
    reach_end_xy=np.array([confluence, confluence, confluence]),
    map_points_xy=np.vstack([main_line, lower_line, side_line]),
)
settings = HeadsSettings(snap_radius_m=60.0, min_drained_area_m2=4 * SIZE * SIZE)
trace = trace_from_heads(
    metric, candidates, cell_area_m2=np.full(N * N, SIZE * SIZE), settings=settings
)

fig, ax = plt.subplots(figsize=(4.6, 4.6))
ax.imshow(
    filled.reshape(N, N), origin="lower", cmap="Greys", alpha=0.4, extent=(0, N * SIZE, 0, N * SIZE)
)
traced = np.flatnonzero(trace.traced)
ax.scatter(x[traced], y[traced], marker="s", s=38, color=ORANGE, alpha=0.75, label="drawn map")
for line in (main_line, lower_line, side_line):
    ax.plot(line[:, 0], line[:, 1], color=BLUE, lw=1.6)
ax.plot([], [], color=BLUE, lw=1.6, label="mapped lines")
kept = {tuple(p) for p in trace.head_xy.tolist()}
for point in candidates.head_xy:
    if tuple(point.tolist()) in kept:
        ax.plot(*point, marker="^", ms=8, color=GREEN)
        ax.add_patch(
            Circle(point, settings.snap_radius_m, fill=False, ls="--", color=GREEN, lw=0.8)
        )
    else:
        ax.plot(*point, marker="x", ms=8, color="0.2", mew=1.6)
landed = trace.head_cell[trace.head_cell >= 0]
ax.scatter(x[landed], y[landed], marker="o", s=60, facecolor="none", edgecolor=GREEN, lw=1.6)
ax.plot([], [], marker="^", ls="", color=GREEN, label="kept head, its radius $r_s$")
ax.plot([], [], marker="x", ls="", color="0.2", label="free end that drains more")
ax.set_xticks([])
ax.set_yticks([])
ax.grid(False)
ax.set_aspect("equal")
ax.legend(fontsize=7, loc="lower left", framealpha=0.9)
fig.tight_layout()
