"""A triangulation, its Voronoi dual and the angle of a connection.

The angles come from connection_nonorthogonality_deg, the dual from
voronoi_dual_of_mesh, on the two examples of the mesh page.
"""

import matplotlib.pyplot as plt
import numpy as np
from scipy.spatial import Delaunay

from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.ops.mesh_orthogonality import connection_nonorthogonality_deg
from hydromodpy.spatial.mesh.ops.voronoi import domain_polygon_from_mesh, voronoi_dual_of_mesh


def triangles(vertices, cells):
    block = CellBlock(cell_type=CellType.TRIANGLE, connectivity=np.asarray(cells, dtype=int))
    return HydroMesh(vertices=np.asarray(vertices, dtype=float), cell_blocks=(block,))


fig, (pair, lattice) = plt.subplots(1, 2, figsize=(6.4, 3.4))

# Two triangles: a 2 x 1 rectangle cut along its diagonal.
corners = np.array([[0.0, 0.0], [2.0, 0.0], [2.0, 1.0], [0.0, 1.0]])
two = triangles(corners, [[0, 1, 3], [1, 2, 3]])
phi = connection_nonorthogonality_deg(two)[0]
for cell, colour in (([0, 1, 3], "C5"), ([1, 2, 3], "C0")):
    pair.fill(*corners[cell].T, fc=(colour, 0.25), ec="C6", lw=1.0)
pair.plot(*corners[[1, 3]].T, color="C1", lw=2.5)
c1, c2 = corners[[0, 1, 3]].mean(axis=0), corners[[1, 2, 3]].mean(axis=0)
pair.annotate("", c2, c1, arrowprops={"arrowstyle": "-|>", "color": "C0", "lw": 1.6})
mid = 0.5 * (corners[1] + corners[3])
normal = np.array([1.0, 2.0]) / np.sqrt(5.0)
pair.annotate(
    "", mid + 0.45 * normal, mid, arrowprops={"arrowstyle": "-|>", "color": "C1", "lw": 1.6}
)
pair.text(*(c1 + [-0.15, -0.22]), r"$\mathbf{d}_{nm}$", color="C0", fontsize=11)
pair.text(*(mid + 0.5 * normal + [-0.05, 0.02]), r"$\mathbf{n}_{nm}$", color="C1", fontsize=11)
pair.set_title(rf"Two triangles: $\varphi_{{nm}}$ = {phi:.1f}°", fontsize=10)

# 36 seeds on a 6 x 6 lattice, the 16 inner ones moved at random.
grid = np.linspace(0.0, 5.0, 6)
seeds = np.array([[x, y] for y in grid for x in grid])
inner = (seeds[:, 0] > 0) & (seeds[:, 0] < 5) & (seeds[:, 1] > 0) & (seeds[:, 1] < 5)
seeds[inner] += np.random.default_rng(3).uniform(-0.35, 0.35, (int(inner.sum()), 2))
tri = triangles(seeds, Delaunay(seeds).simplices)
dual = voronoi_dual_of_mesh(tri, domain_polygon_from_mesh(tri))
angles_tri = connection_nonorthogonality_deg(tri)
angles_dual = connection_nonorthogonality_deg(dual)
for cell in tri.flat_connectivity:
    lattice.fill(*seeds[cell].T, fc="none", ec="C6", lw=0.6, ls=":")
for cell in dual.flat_connectivity:
    polygon = np.asarray(dual.vertices)[np.asarray(cell)]
    lattice.fill(*polygon.T, fc=("C5", 0.25), ec="C0", lw=1.4)
lattice.plot(*seeds.T, "o", color="C6", ms=3)
lattice.set_title(
    f"{tri.n_cells} triangles, {dual.n_cells} dual cells\n"
    f"largest angle: {angles_tri.max():.0f}° and {angles_dual.max():.0f}°",
    fontsize=10,
)

for ax in (pair, lattice):
    ax.set_aspect("equal")
    ax.axis("off")
fig.tight_layout()
