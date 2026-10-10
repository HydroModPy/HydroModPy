# Dupuit Circular-Island Ocean 2D

Steady synthetic groundwater-flow case used to validate the launcher workflow
against the axisymmetric Dupuit-Boussinesq solution for a circular island with:

- uniform recharge over the island,
- one flat impermeable substratum,
- sea level imposed through HydroModPy's `ocean` boundary condition,
- no salt wedge and no density correction.

Intent:

- validate the `ocean` boundary condition on a genuinely 2D synthetic geometry,
- verify that the numerical solution preserves radial symmetry on a Cartesian grid,
- keep an analytical benchmark where the water table remains below the island topography.

Comparison:

- simulated observable: `watertable_elevation`
- compared quantity: annular mean head profile on land
- reference: steady radial Dupuit-Boussinesq solution with fixed coastal head
- for `solver=boussinesq` and `boussinesq_local`, the runtime meshes the island
  with near-equilateral triangles of 10 m (a node ring on the coast, one ring
  of ocean triangles at the sea level), and the profile is read on the
  triangles, the reference at each centroid
- for `solver=modflow6_voronoi`, the profile is read on the solver cells, which
  are centred on the nodes of the mesh bundle, in 5 m bins that each hold one
  node ring; a node ring lies on the coast, where the model must hold the sea
  level, so this run reads a 1 m DEM whose shoreline sits 1 m inside that ring
  and every coast cell takes the ocean head (a node on the shoreline itself is
  a tie that the DEM sampling breaks at random)

Direct execution:

```bash
python -m validation_cases.analytical.steady.dupuit_circular_island_ocean_2d.run_case
```

The runner saves a PNG figure with:

- the synthetic DEM and shoreline,
- the final land water-table map,
- the numerical annular profile against the analytical reference,
- the residual curve and summary metrics.

## Equations

The equations of the reference solution the comparison uses.

$$
\frac{1}{r}\frac{\mathrm{d}}{\mathrm{d}r}\left(r\,K\,H\,\frac{\mathrm{d}H}{\mathrm{d}r}\right)+R=0
$$

$$
H(r)^2=H(a)^2+\frac{R}{2K}\left(a^2-r^2\right)
$$

$$
h(r)=z_b+\sqrt{\left(h_{\mathrm{sea}}-z_b\right)^2+\frac{R}{2K}\left(a^2-r^2\right)}
$$
