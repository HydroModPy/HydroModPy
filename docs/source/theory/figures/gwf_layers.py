"""Layer interfaces of a 100 m column, drawn by _compute_layer_proportions."""

import matplotlib.pyplot as plt
import numpy as np

from hydromodpy.solver.modflow_grid.discretization_spatial import _compute_layer_proportions

H = 100.0
rules = [
    ("constant", {"genmtd_lay": "constant", "nlay": 4}),
    ("decay\n" + r"$\rho = 2$", {"genmtd_lay": "decay", "nlay": 4, "lay_decay": 2.0}),
    ("decay\n" + r"$\rho = 4$", {"genmtd_lay": "decay", "nlay": 4, "lay_decay": 4.0}),
    ("list\n0.1, 0.2, 0.3, 0.4", {"genmtd_lay": "list", "lay_proportions": [0.1, 0.2, 0.3, 0.4]}),
]

fig, ax = plt.subplots(figsize=(6.4, 3.8))
for i, (_label, keys) in enumerate(rules):
    keys = {"nlay": None, "lay_decay": None, "lay_proportions": None, **keys}
    shares, nlay = _compute_layer_proportions(**keys)
    bottoms = H * np.asarray(shares)
    tops = np.concatenate(([0.0], bottoms[:-1]))
    for j in range(nlay):
        ax.bar(
            i,
            bottoms[j] - tops[j],
            bottom=tops[j],
            width=0.6,
            color="C5" if j % 2 == 0 else "C0",
            alpha=0.55 if j % 2 == 0 else 0.45,
            edgecolor="C6",
            lw=0.8,
        )
        thick = bottoms[j] - tops[j]
        middle = 0.5 * (tops[j] + bottoms[j])
        if thick >= 6.0:
            ax.text(i, middle, f"{thick:.3g} m", ha="center", va="center")
        else:
            ax.text(i + 0.32, middle + 2.5 * (j - 0.5), f"{thick:.2g} m", va="center", fontsize=8)
ax.set_xticks(range(len(rules)), [label for label, _ in rules])
ax.set_ylim(H, 0)
ax.set_ylabel("depth below the top (m)")
ax.grid(axis="x", visible=False)
ax.set_title(r"Four layers in a column of thickness $H = 100$ m", fontsize=10)
fig.tight_layout()
