"""The exponential depth factor, drawn by FieldParam.vertical_factor."""

import matplotlib.pyplot as plt
import numpy as np

from hydromodpy.solver.modflow_grid.discretization_spatial import _compute_layer_proportions
from hydromodpy.spatial.field.core.field_param import FieldParam

H = 100.0
profile = {"mode": "exponential", "characteristic_depth": 20.0}
plain = FieldParam(identifier="K", kind="homogeneous", value=1e-5, vertical_profile=profile)
floored = FieldParam(
    identifier="K",
    kind="homogeneous",
    value=1e-5,
    vertical_profile={**profile, "min_factor": 0.05},
)

# Layer centres of a four-layer decay column, as SolverMesh.layer_center_depths
# computes them: halfway between the two interfaces.
shares, _ = _compute_layer_proportions(
    genmtd_lay="decay", nlay=4, lay_decay=2.0, lay_proportions=None
)
bottoms = H * shares
centres = 0.5 * (np.concatenate(([0.0], bottoms[:-1])) + bottoms)

d = np.linspace(0.0, H, 400)
fig, ax = plt.subplots(figsize=(6.4, 3.8))
for z in bottoms[:-1]:
    ax.axhline(z, color="C6", lw=0.6, ls=":")
ax.plot(plain.vertical_factor(d), d, color="C0", lw=1.6, label=r"$f_\mathrm{min}$ unset")
ax.plot(
    floored.vertical_factor(d), d, color="C1", lw=1.6, ls="--", label=r"$f_\mathrm{min} = 0.05$"
)
f_layers = floored.vertical_factor(centres)
ax.plot(f_layers, centres, "o", color="C1", ms=6, label="value of each layer")
for f, dj in zip(f_layers, centres, strict=True):
    ax.annotate(f"$f = {f:.2f}$", (f, dj), xytext=(8, 0), textcoords="offset points", va="center")
ax.set_ylim(H, 0)
ax.set_xlim(0, 1.05)
ax.set_xlabel(r"depth factor $f(d)$")
ax.set_ylabel(r"depth below the top $d$ (m)")
ax.set_title(r"$d_c = 20$ m; dotted lines: the interfaces of four decay layers", fontsize=10)
ax.legend(loc="lower right", frameon=False)
fig.tight_layout()
