"""How many cells a size costs, for the three layouts of eq-cell-count."""

import matplotlib.pyplot as plt
import numpy as np

# The domain of the worked example: 21406 cells of 75 m.
DELTA = 75.0
AREA = 21406 * DELTA**2
sizes = np.logspace(np.log10(20.0), np.log10(500.0), 200)
layouts = [
    ("square pixels, side $\\Delta$", 1.0, "C6", "-", (-34, -16)),
    ("Voronoi cells, seeds $\\ell$ apart", 2.0 / np.sqrt(3.0), "C0", "--", (8, -16)),
    ("triangles, side $\\ell$", 4.0 / np.sqrt(3.0), "C1", "-.", (4, 6)),
]

fig, ax = plt.subplots(figsize=(6.4, 3.6))
target = AREA / DELTA**2
for label, factor, colour, style, offset in layouts:
    ax.loglog(sizes, factor * AREA / sizes**2, color=colour, ls=style, lw=1.8, label=label)
    size = np.sqrt(factor * AREA / target)
    ax.plot(size, target, "o", color=colour, ms=6)
    ax.annotate(f"{size:.0f} m", (size, target), xytext=offset, textcoords="offset points")
ax.axhline(target, color="C6", lw=0.8, ls=":")
ax.set_xticks([20, 50, 100, 200, 500], ["20", "50", "100", "200", "500"])
ax.minorticks_off()
ax.set_xlabel(r"cell size $\Delta$ or $\ell$ (m)")
ax.set_ylabel("number of cells")
ax.set_title(
    rf"$A_\Omega$ = {AREA / 1e6:.0f} km$^2$; dots: {target:.0f} cells for each layout",
    fontsize=10,
)
ax.legend(loc="upper right", frameon=False)
fig.tight_layout()
