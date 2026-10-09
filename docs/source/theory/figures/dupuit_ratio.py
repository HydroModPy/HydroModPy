"""The Dupuit ratio beta (B / L_h)^2 over aspect ratio and anisotropy."""

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import BoundaryNorm, ListedColormap

aspect = np.logspace(np.log10(0.003), np.log10(0.5), 300)  # B / L_h
beta = np.logspace(0, 3, 300)  # K / K_z
A, BETA = np.meshgrid(aspect, beta)
ratio = BETA * A**2

levels = [1e-8, 0.01, 0.1, 1.0, 1e8]
colors = ["#ffffff", "#cfe6f5", "#f6d3b8", "#e6997a"]
fig, ax = plt.subplots(figsize=(6.4, 3.8))
ax.contourf(
    A, BETA, ratio, levels=levels, cmap=ListedColormap(colors), norm=BoundaryNorm(levels, 4)
)
ax.contour(A, BETA, ratio, levels=levels[1:4], colors="C6", linewidths=1.0)
for level in levels[1:4]:
    ax.text(1.1 * np.sqrt(level / 100.0), 100.0, f"{level:g}", fontsize=9, va="bottom")
ax.set_xscale("log")
ax.set_yscale("log")
ax.grid(False)

# A 30 m thick aquifer under hillslopes of 500 m and 100 m.
for length, text in [(500.0, r"$L_h = 500$ m"), (100.0, r"$L_h = 100$ m")]:
    point = (30.0 / length, 10.0)
    ax.plot(*point, "o", color="C1", ms=6)
    value = point[1] * point[0] ** 2
    ax.annotate(
        f"{text}: {value:.2g}", point, xytext=(6, 6), textcoords="offset points", fontsize=9
    )
ax.text(0.004, 1.4, "Dupuit is fair", fontsize=10)
ax.text(0.12, 300, "Dupuit fails", fontsize=10)
ax.set_xlabel(r"aspect ratio $B / L_h$")
ax.set_ylabel(r"anisotropy $\beta = K / K_z$")
ax.set_title(r"$\beta\,(B / L_h)^2$, with $B = 30$ m and $\beta = 10$ marked", fontsize=10)
fig.tight_layout()
