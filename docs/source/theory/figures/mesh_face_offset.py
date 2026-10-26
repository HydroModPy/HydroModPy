"""The two assumptions of the two-point flux on one face: angle and bisection offset.

Left: two Voronoi cells whose generators sit off the middle of their face. The
line of the centres is normal to the face but crosses it off its middle.
Right: the two triangles of the angle example. The line crosses the face in its
middle but is not normal to it. Both measures come from mesh_qa.
"""

import matplotlib.pyplot as plt
import numpy as np
from shapely.geometry import box

from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.derived_geometry import derive_geometry
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.model.mesh_qa import edge_bisection_offset, edge_nonorthogonality
from hydromodpy.spatial.mesh.ops.voronoi import voronoi_planar_mesh


def measures(mesh):
    """Angle and bisection offset of the one interior face of a two-cell mesh."""
    vertices = np.asarray(mesh.vertices, dtype=float)[:, :2]
    centres = np.column_stack(mesh.cell_centroids())
    geometry = derive_geometry(mesh)
    keep = geometry.edge_cells[:, 1] >= 0
    face = int(np.flatnonzero(keep)[0])
    phi = edge_nonorthogonality(centres, vertices, geometry, keep)[face]
    beta = edge_bisection_offset(centres, vertices, geometry, keep)[face]
    return vertices, centres, vertices[geometry.edge_nodes[face]], phi, beta


def draw(ax, mesh, title):
    vertices, centres, face, phi, beta = measures(mesh)
    for cell, colour in zip(mesh.flat_connectivity, ("C5", "C0"), strict=True):
        ax.fill(*vertices[np.asarray(cell)].T, fc=(colour, 0.2), ec="C6", lw=0.8)
    ax.plot(*face.T, color="C1", lw=2.5)
    ax.annotate(
        "", centres[1], centres[0], arrowprops={"arrowstyle": "-|>", "color": "C0", "lw": 1.6}
    )
    ax.plot(*centres.T, "o", color="C0", ms=5)
    middle = face.mean(axis=0)
    ax.plot(*middle, "s", color="C1", ms=5)
    ax.set_title(
        f"{title}\n" + rf"$\varphi_{{nm}}$ = {phi:.1f}°, $\beta$ = {beta:.2f}", fontsize=10
    )
    ax.set_aspect("equal")
    ax.axis("off")
    return face, middle


fig, (pebi, tri) = plt.subplots(1, 2, figsize=(6.4, 3.0))

# Two Voronoi cells, generators 0.6 above the middle of their face.
seeds = np.array([[1.0, 1.6], [3.0, 1.6]])
face, middle = draw(pebi, voronoi_planar_mesh(seeds, box(0.0, 0.0, 4.0, 2.0)), "Voronoi cells")
crossing = np.array([2.0, 1.6])
pebi.annotate(
    "", crossing + [0.15, 0.0], middle + [0.15, 0.0], arrowprops={"arrowstyle": "<->", "lw": 1.0}
)
pebi.text(*(middle + [0.22, 0.2]), r"$\beta L$", fontsize=10)
pebi.text(*(face[0] + [0.08, 0.05]), "face, length $L$", color="C1", fontsize=8)

# The two triangles of a 2 x 1 rectangle cut along its diagonal.
corners = np.array([[0.0, 0.0], [2.0, 0.0], [2.0, 1.0], [0.0, 1.0]])
block = CellBlock(cell_type=CellType.TRIANGLE, connectivity=np.array([[0, 1, 3], [1, 2, 3]]))
draw(tri, HydroMesh(vertices=corners, cell_blocks=(block,)), "Two triangles")
fig.tight_layout()
