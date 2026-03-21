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
- for `solver=boussinesq`, the comparison is limited to `r <= 180 m` because the
  current local backend needs a thin explicit ocean-support ring at the shoreline

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
