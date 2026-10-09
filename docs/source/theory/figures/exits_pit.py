"""The 3 by 3 pit of the routing page, drawn from one call of build_descent."""

import matplotlib.pyplot as plt
import numpy as np

from hydromodpy.core.descent import build_descent

NROW, NCOL, SIZE = 3, 3, 10.0
# Tops in metres. Row 0 is the south row, so north is up on the figure.
TOP = np.array([[5.0, 4.0, 5.0], [5.0, 3.0, 5.0], [5.0, 5.0, 5.0]])


def quad_mesh(nrow, ncol, size):
    """Vertices and face-node connectivity of a grid of square cells."""
    corner = (np.arange(nrow)[:, None] * (ncol + 1) + np.arange(ncol)[None, :]).ravel()
    faces = np.column_stack([corner, corner + 1, corner + ncol + 2, corner + ncol + 1])
    xx, yy = np.meshgrid(np.arange(ncol + 1) * size, np.arange(nrow + 1) * size)
    return np.column_stack([xx.ravel(), yy.ravel(), np.zeros(xx.size)]), faces


vertices, faces = quad_mesh(NROW, NCOL, SIZE)
rows, cols = np.divmod(np.arange(NROW * NCOL), NCOL)
centres = np.column_stack([(cols + 0.5) * SIZE, (rows + 0.5) * SIZE])
descent = build_descent(
    TOP.ravel(),
    faces,
    vertices=vertices,
    centroids=centres,
    routable=np.ones(NROW * NCOL, dtype=bool),
)

fig, axes = plt.subplots(1, 2, figsize=(6.4, 3.2))
for ax, values, title in (
    (axes[0], TOP.ravel(), "Model top $z_\\mathrm{top}$ (m)"),
    (axes[1], descent.surface, "Filled copy $\\tilde z$ and receivers"),
):
    ax.imshow(
        values.reshape(NROW, NCOL),
        origin="lower",
        extent=(0, NCOL * SIZE, 0, NROW * SIZE),
        cmap="Blues_r",
        vmin=1.0,
        vmax=5.5,
    )
    for cell, (x, y) in enumerate(centres):
        label = (
            f"{values[cell]:.3f}" if descent.raised[cell] and ax is axes[1] else f"{values[cell]:g}"
        )
        ax.text(x, y + 2.6, label, ha="center", va="center", fontsize=9)
    ax.set_title(title, fontsize=10)
    ax.set_xticks(np.arange(0, NCOL * SIZE + 1, SIZE))
    ax.set_yticks(np.arange(0, NROW * SIZE + 1, SIZE))
    ax.tick_params(labelbottom=False, labelleft=False, length=0)
    ax.grid(True, color="0.4", alpha=0.6)
    ax.set_aspect("equal")

receiver = descent.receiver
for cell, target in enumerate(receiver):
    x, y = centres[cell]
    if target < 0:
        axes[1].plot(x, y - 1.0, "o", color="#D55E00", ms=7)
        continue
    dx, dy = centres[target] - centres[cell]
    axes[1].annotate(
        "",
        xy=(x + 0.62 * dx, y - 1.0 + 0.62 * dy),
        xytext=(x, y - 1.0),
        arrowprops={"arrowstyle": "-|>", "color": "#D55E00", "lw": 1.4},
    )
axes[1].text(15, -1.0, "dot: no receiver, water leaves here", ha="center", va="top", fontsize=8)
fig.tight_layout()
