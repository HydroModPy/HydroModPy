"""Two triangles of the Boussinesq solver and the flux through their edge."""

from types import SimpleNamespace

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Polygon

from hydromodpy.solver.boussinesq.assembly.fluxes import internal_edge_flux_from_head

tri_a = np.array([[0.0, 0.0], [2.0, 0.0], [0.6, 1.6]])
tri_b = np.array([[2.0, 0.0], [2.4, 1.7], [0.6, 1.6]])
centre_a, centre_b = tri_a.mean(axis=0), tri_b.mean(axis=0)
edge = np.array([[2.0, 0.0], [0.6, 1.6]])
L_e = float(np.hypot(*(edge[1] - edge[0])))
d_e = float(np.hypot(*(centre_b - centre_a)))

fig, (plan, flux) = plt.subplots(1, 2, figsize=(6.4, 3.3))
plan.add_patch(Polygon(tri_a, fc="C5", alpha=0.35, ec="C6"))
plan.add_patch(Polygon(tri_b, fc="C0", alpha=0.25, ec="C6"))
plan.plot(*edge.T, color="C1", lw=3.0)
plan.plot(*np.array([centre_a, centre_b]).T, "o--", color="C6", ms=5, lw=1.2)
plan.text(*(centre_a + [-0.1, -0.3]), "$a$", fontsize=13)
plan.text(*(centre_b + [0.05, 0.15]), "$b$", fontsize=13)
plan.text(1.82, 0.3, "$L_e$", color="C1", fontsize=12)
plan.text(*(0.5 * (centre_a + centre_b) + [-0.4, 0.12]), "$d_e$", fontsize=12)
plan.set_xlim(-0.1, 2.5)
plan.set_ylim(-0.1, 1.8)
plan.set_aspect("equal")
plan.axis("off")
plan.set_title("Centroids and the shared edge", fontsize=10)

# Cell b sits higher on a sloping bottom and drains into a. Its head goes down
# to its bottom; the head of a stays 5 m above its own bottom.
heads_b = np.linspace(6.0, 9.0, 61)
mesh = SimpleNamespace(
    n_edges=1,
    z_bottom_m=np.array([0.0, 6.0]),
    z_top_m=np.array([10.0, 16.0]),
    hydraulic_conductivity_m_s=np.array([1e-5, 1e-5]),
    edge_cell_a=np.array([0]),
    edge_cell_b=np.array([1]),
    edge_length_m=np.array([L_e * 50.0]),
    edge_distance_m=np.array([d_e * 50.0]),
)
code = np.array([-internal_edge_flux_from_head(mesh, [5.0, h])[0] for h in heads_b])
B_b = heads_b - 6.0
donor = 1e-5 * B_b * (L_e / d_e) * (heads_b - 5.0)
flux.plot(B_b, code * 1e3, color="C1", lw=2.0, label=r"the code: $\bar B_e = (B_a + B_b)/2$")
flux.plot(B_b, donor * 1e3, color="C6", lw=1.2, ls="--", label=r"thickness of $b$ only")
flux.set_xlabel(r"saturated thickness of $b$, $B_b$ (m)")
flux.set_ylabel(r"flow from $b$ to $a$ (L/s)")
flux.set_title(r"$b$ gives water even when dry", fontsize=10)
flux.set_xlim(0, 3)
flux.set_ylim(0, None)
flux.legend(loc="upper left", fontsize=8, frameon=False)
fig.tight_layout()
