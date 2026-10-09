# Boussinesq Circular-Island Piecewise-K 2D

Steady synthetic groundwater-flow case used to validate the launcher workflow
against the axisymmetric Dupuit-Boussinesq solution for a circular island with:

- uniform recharge over the island,
- one flat impermeable substratum,
- sea level imposed through HydroModPy's `ocean` boundary condition,
- concentric piecewise-constant hydraulic conductivity on land,
- no salt wedge and no density correction.

Intent:

- validate heterogeneous `K` mapping on a genuinely 2D synthetic geometry,
- verify that the numerical solution preserves radial symmetry on a Cartesian grid,
- keep an analytical benchmark where the water table remains below the island topography.

Comparison:

- simulated observable: `watertable_elevation`
- compared quantity: annular mean head profile on land
- reference: steady radial Boussinesq solution with concentric piecewise `K`
- for `solver=boussinesq` and `boussinesq_local`, the runtime meshes the island
  with near-equilateral triangles of 10 m (a node ring on the coast and on each
  K break, one ring of ocean triangles at the sea level), and the profile is
  read on the triangles, the reference at each centroid
- for `solver=modflow6_voronoi`, the profile is read on the solver cells, which
  are centred on the nodes of the mesh bundle, in 5 m bins that each hold one
  node ring

Direct execution:

```bash
python -m validation_cases.analytical.steady.boussinesq_circular_island_piecewise_k_2d.run_case
python -m validation_cases.analytical.steady.boussinesq_circular_island_piecewise_k_2d.run_case --solver boussinesq
```

The runner saves a PNG figure with:

- the synthetic DEM and shoreline,
- the final land water-table map,
- the numerical annular profile against the analytical reference,
- the residual curve and summary metrics.

## Equations

The equations of the reference solution the comparison uses.

$$
\frac{1}{r}\frac{\mathrm{d}}{\mathrm{d}r}\left(r\,K(r)\,H\,\frac{\mathrm{d}H}{\mathrm{d}r}\right)+R=0
$$

$$
U=H^2,\qquad U(r)=U(a)+R\int_r^a \frac{s}{K(s)}\,\mathrm{d}s
$$
