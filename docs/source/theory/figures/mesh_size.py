"""The cell size against the distance to an interface, with the bounds Gmsh gets.

apply_mesh_options sets the two bounds on Gmsh; the stub below records them.
The sizes are those of the test quoted under Limits on the mesh page.
"""

from types import SimpleNamespace

import matplotlib.pyplot as plt
import numpy as np

from hydromodpy.spatial.mesh.gmsh_grid.zone_meshing._gmsh_occ import apply_mesh_options

L_S, L_G, XI_S = 20.0, 100.0, 300.0


def bounds(min_size):
    """MeshSizeMin and MeshSizeMax as apply_mesh_options sets them."""
    options = {}
    stub = SimpleNamespace(option=SimpleNamespace(setNumber=options.__setitem__))
    apply_mesh_options(stub, algorithm="frontal", global_size=L_G, min_size=min_size, max_size=None)
    return options["Mesh.MeshSizeMin"], options["Mesh.MeshSizeMax"]


xi = np.linspace(0.0, 500.0, 501)
wanted = L_S + (L_G - L_S) * np.minimum(1.0, xi / XI_S)
fig, ax = plt.subplots(figsize=(6.4, 3.4))
ax.plot(xi, wanted, color="C6", lw=1.0, ls=":", label=r"$\ell_0(\xi)$, the size field")
for min_size, color, style, text in [
    (None, "C1", "-", r"min_size unset: $\ell_{\min}' = \ell_g$"),
    (20.0, "C0", "--", r"min_size = 20 m"),
]:
    low, high = bounds(min_size)
    ax.plot(xi, np.clip(wanted, low, high), color=color, ls=style, lw=2.0, label=text)
ax.fill_between(xi, wanted, L_G, color="C1", alpha=0.12, lw=0)
ax.text(40, 82, "refinement lost\nwithout min_size", color="C1", fontsize=9)
ax.set_xlabel(r"distance to the interface $\xi$ (m)")
ax.set_ylabel(r"cell size $\ell$ (m)")
ax.set_ylim(0, 115)
ax.set_title(r"$\ell_s$ = 20 m, $\ell_g$ = 100 m, $\xi_s$ = 300 m", fontsize=10)
ax.legend(loc="lower right", frameon=False)
fig.tight_layout()
