# Patch test on skewed triangles

The minimal consistency check of a finite-volume scheme: a scheme that cannot
carry a uniform flow on a mesh does not converge on it.

Setup:

- strip of 100 x 40 m, 10 m squares cut along one diagonal, the nodes of the
  inner columns moved by up to 3 m in x and 2.5 m in y: 80 skewed triangles,
  none isosceles (`mesh.py` writes the bundle under
  `validation_cases/shared/mesh_bundles/patch_test_skewed_triangles_100x40`),
- heads of 50.2 m on the west edge and 50.0 m on the east edge, held at the
  centroids of the triangles that own those edges (x = 10/3 and 100 - 10/3 m);
  on the Voronoi dual, one cell per node, they are held on the nodes of the
  faces (x = 0 and 100 m),
  no-flow north and south, no recharge,
- an aquifer from -1000 to 1000 m with K = 1e-4 m/s: the transmissivity is
  uniform to 2e-4,
- variants: MODFLOW 6 on the triangles with XT3D, the same with XT3D off, MODFLOW
  6 on the Voronoi dual of the same nodes, and the Boussinesq solver with its
  default local engine and with its PETSc engine. MODFLOW-NWT and the structured
  MODFLOW 6 grid are rectangular grids with no skewed cells: not applicable.

Reference: the steady head of a uniform flow, at every triangle centroid.

Expected: XT3D and the Voronoi dual reproduce it to the solver closure (the dual
is orthogonal, so its two-point flux is exact for a uniform flow); the two-point
flux between triangle centroids, in MODFLOW 6 without XT3D and in the Boussinesq
solver (both engines assemble the same residual), does not, and the error does
not fall with the cell size. The two-point variants carry a documented gap.

## Equations

The equations of the reference solution the comparison uses.

$$
\left(h(x)-z_b\right)^2=\left(h_W-z_b\right)^2+\left[\left(h_E-z_b\right)^2-\left(h_W-z_b\right)^2\right]\frac{x-x_W}{x_E-x_W}
$$
