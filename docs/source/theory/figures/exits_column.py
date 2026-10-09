"""A cross-section of five columns, each with the exit HydroModPy builds there."""

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from hydromodpy.solver.modflow_common.drain_conductance import drain_discharge_band

BLUE, ORANGE, GREEN, PINK, YELLOW = "#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00"
WIDTH = 1.0
TOPS = (2.0, 4.0, 4.6, 3.4, 3.2)  # model top of each column, m
LAYERS = (-6.0, -3.0, 0.0)  # bottoms of layers 3, 2, 1, m
BAND = 0.6  # drain band depth, m

fig, ax = plt.subplots(figsize=(6.4, 3.8))
ax.grid(False)
for col, top in enumerate(TOPS):
    x0 = col * WIDTH
    bottoms = (LAYERS[2], LAYERS[1], LAYERS[0])
    upper = (top, LAYERS[2], LAYERS[1])
    for layer, (z_top, z_bot) in enumerate(zip(upper, bottoms, strict=True)):
        inactive = col == 4 and layer == 0
        ax.add_patch(
            Rectangle(
                (x0, z_bot),
                WIDTH,
                z_top - z_bot,
                facecolor="white" if inactive else "0.93",
                edgecolor="0.5",
                hatch="//" if col == 0 else None,
            )
        )

# Column 0: a fixed head in every layer.
ax.text(0.5, -7.0, "CHD\nevery layer", ha="center", va="top", fontsize=8, color=BLUE)
ax.plot([0.0, 1.0], [2.0, 2.0], color=BLUE, lw=2)

# Column 1: a drain at the top minus half the band, and the ET surface.
elevation, _ = drain_discharge_band(top=4.0, conductance=1.0, bed_thickness=1.0, band_depth=BAND)
ax.plot([1.15, 1.85], [elevation, elevation], color=ORANGE, lw=2.5)
ax.annotate(
    "drain at $z_\\mathrm{top} - \\delta/2$",
    xy=(1.5, elevation),
    xytext=(0.15, 6.3),
    fontsize=8,
    color=ORANGE,
    arrowprops={"arrowstyle": "-", "color": ORANGE, "lw": 0.8},
)
ax.plot([1.05, 1.95], [elevation - 1.0, elevation - 1.0], color=GREEN, lw=1.2, ls="--")
ax.text(
    1.5,
    elevation - 1.1,
    "ET stops at $d_\\mathrm{ext}$",
    ha="center",
    va="top",
    fontsize=7,
    color=GREEN,
)

# Column 2: a reach, its bed inside its own cell.
bed_top, bed_thick = 4.6 - 0.5, 0.4
ax.add_patch(
    Rectangle((2.3, bed_top - bed_thick), 0.4, bed_thick, facecolor=YELLOW, edgecolor="0.3")
)
ax.add_patch(Rectangle((2.3, bed_top), 0.4, 0.3, facecolor=BLUE, alpha=0.45, edgecolor="none"))
ax.text(2.5, 6.3, "SFR reach\n(no drain row)", ha="center", va="bottom", fontsize=8, color="0.2")

# Columns 3 and 4: a lake over an inactive top layer, two kinds of connection.
ax.add_patch(Rectangle((4.0, 0.0), 1.0, 3.6, facecolor=BLUE, alpha=0.35, edgecolor="none"))
ax.text(4.5, 3.9, "lake (LAK)", ha="center", va="bottom", fontsize=8, color=BLUE)
ax.annotate(
    "", xy=(4.5, -1.3), xytext=(4.5, 0.4), arrowprops={"arrowstyle": "<|-|>", "color": PINK}
)
ax.annotate(
    "", xy=(3.55, 1.6), xytext=(4.45, 1.6), arrowprops={"arrowstyle": "<|-|>", "color": PINK}
)
ax.text(4.55, -0.6, "vertical", fontsize=7, color=PINK, va="center")
ax.text(4.0, 1.85, "bank", fontsize=7, color=PINK, ha="center")

# The water table.
ax.plot([0.0, 1.0, 2.0, 3.0, 4.0, 5.0], [2.0, 3.75, 4.05, 3.3, 3.6, 3.6], color=BLUE, lw=1.0)
ax.text(3.05, 2.95, "water table", fontsize=7, color=BLUE)

ax.set_xlim(-0.1, 5.1)
ax.set_ylim(-8.2, 7.6)
ax.set_xticks([])
ax.set_ylabel("elevation (m)")
for side in ("top", "right", "bottom"):
    ax.spines[side].set_visible(False)
fig.tight_layout()
