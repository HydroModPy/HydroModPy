"""The three connections HydroModPy writes to the MODFLOW 6 water mover."""

import matplotlib.pyplot as plt

from hydromodpy.solver.modflow6.builders.mvr import MVR_TYPES

NODES = {  # name: (x, y, package)
    "drain": (0.0, 1.0, "DRN"),
    "reach": (1.0, 1.0, "SFR or LAK"),
    "terminal": (2.0, 1.0, "SFR"),
    "lake": (3.0, 1.0, "LAK"),
    "outlet": (3.0, 0.0, "LAK"),
    "next": (2.0, 0.0, "SFR or LAK"),
}
LABELS = {
    "drain": "drain cell\nof the basin",
    "reach": "first reach or\nlake met on D",
    "terminal": "terminal\nreach",
    "lake": "lake",
    "outlet": "lake outlet",
    "next": "dam-foot reach,\nanother lake",
}
EDGES = (  # provider, receiver, rule, key
    ("drain", "reach", "FACTOR 1", "route_drainage"),
    ("terminal", "lake", "rule of the network", "outflow_to_lake"),
    ("outlet", "next", "rule of the outlet", "outlets.mover.mvrtype"),
)
ROUTED = ("reach", "terminal")  # SFR routes the water itself, not the mover

fig, ax = plt.subplots(figsize=(6.4, 2.9))
ax.axis("off")
for name, (x, y, package) in NODES.items():
    ax.text(
        x,
        y,
        f"{LABELS[name]}\n[{package}]",
        ha="center",
        va="center",
        fontsize=8,
        bbox={"boxstyle": "round,pad=0.4", "facecolor": "0.95", "edgecolor": "0.4"},
    )
for provider, receiver, rule, key in EDGES:
    (x0, y0, _), (x1, y1, _) = NODES[provider], NODES[receiver]
    ax.annotate(
        "",
        xy=(x1 - 0.32 * (x1 - x0), y1 - 0.32 * (y1 - y0)),
        xytext=(x0 + 0.32 * (x1 - x0), y0 + 0.32 * (y1 - y0)),
        arrowprops={"arrowstyle": "-|>", "color": "#D55E00", "lw": 1.6},
    )
    xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
    ax.text(xm, ym + 0.2, f"{rule}\n{key}", ha="center", va="bottom", fontsize=7, color="#D55E00")
(x0, y0, _), (x1, y1, _) = NODES[ROUTED[0]], NODES[ROUTED[1]]
ax.annotate(
    "",
    xy=(x1 - 0.32, y1),
    xytext=(x0 + 0.32, y0),
    arrowprops={"arrowstyle": "-|>", "color": "0.5", "lw": 1.0, "ls": "--"},
)
ax.text((x0 + x1) / 2, y0 - 0.22, "routed by SFR", ha="center", va="top", fontsize=7, color="0.4")
ax.text(
    0.0,
    -0.15,
    "MVR rules: " + ", ".join(MVR_TYPES),
    ha="center",
    va="top",
    fontsize=7,
    color="0.3",
)
ax.set_xlim(-0.5, 3.5)
ax.set_ylim(-0.5, 1.55)
fig.tight_layout()
