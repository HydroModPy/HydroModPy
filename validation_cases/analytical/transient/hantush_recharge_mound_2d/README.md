# Hantush Recharge Mound 2D

Transient synthetic case that validates the growth of a groundwater mound under
a rectangle of uniform recharge against Hantush (1967).

Numerical setup:

- geometry: square domain of 2020 m, `101 x 101` cells of 20 m on the
  structured grids, single layer, aquifer base at 0 m and top at 60 m,
- flow regime: transient unconfined flow, 40 stress periods of 6 h (10 days),
  one time step each,
- recharge: 20 mm/day on the rectangle `300 m x 180 m` centred in the domain,
  zero elsewhere, read from the raster `recharge_zone.tif` as a custom
  recharge source (`[[data.recharge.sources]] source = "custom"`), the route a
  run takes for any recharge map,
- aquifer: `K = 4e-5 m/s`, `Sy = 0.15`, initial head 50 m (saturated
  thickness `hi = 50 m`),
- all outer boundaries: fixed at 50 m, 860 m from the rectangle, four times
  the spreading length `sqrt(4 nu t)` at 10 days,
- simulated observable: `watertable_elevation`.

The raster has the pixels of the structured grid and a mesh cell takes the
pixel under its centroid. A mesh gets the recharge over exactly the rectangle
area only when no cell straddles an edge, so the two meshes are built for it
(`build_inputs.py`): the triangles of
`hantush_recharge_mound_tri_conforming` have the rectangle edges as mesh
lines, and the nodes of `hantush_recharge_mound_voronoi_frames` face each
other across each edge, which puts the Voronoi edges on it. Both are refined
to 10 m under the rectangle, 80 m at the sides. With MODFLOW 6 on the three
grids, MODFLOW-NWT and both Boussinesq engines, the stored volume
`Sy sum(dh A)` equals the recharged volume within 2e-4 at day 10.

Comparison:

- the head rise at the centre over time,
- the head on the transect through the centre along the long side of the
  rectangle, 600 m each way, every 6 h,
- the head of every cell at the final time, on the plan-view map,
- each head against the reference read at the centre of the solver cell that
  holds it: the cell centre, the triangle centroid, the Voronoi node.

The mound reaches 0.75 m, 1.5 % of the saturated thickness, so the
linearization holds: a finite-difference solution of the nonlinear Boussinesq
equation on cells of 6.7 m and steps of 45 min stays within 1.1 mm of the
reference, against 4.8 mm for the case grid.

Run manually:

```bash
python -m validation_cases.analytical.transient.hantush_recharge_mound_2d.run_case
```

Reference used by the documentation:

- reference: Hantush (1967) mound under a rectangle of uniform recharge,
  linearized with the mean saturated thickness `b = (hi + hm(t)) / 2` taken at
  the centre `hm`, solved at each time; `S*` integrated with
  `scipy.integrate.quad_vec`. Carleton (2010, USGS SIR 2010-5102) gives the
  same form.

## Equations

The equations of the reference solution the comparison uses.

$$
h^2-h_i^2=\frac{w}{2K}\,\nu t\left[S^*\!\left((l+x)n,(a+y)n\right)+S^*\!\left((l+x)n,(a-y)n\right)+S^*\!\left((l-x)n,(a+y)n\right)+S^*\!\left((l-x)n,(a-y)n\right)\right]
$$

$$
S^*(\alpha,\beta)=\int_0^1\operatorname{erf}\left(\frac{\alpha}{\sqrt{\tau}}\right)\operatorname{erf}\left(\frac{\beta}{\sqrt{\tau}}\right)d\tau,\qquad \nu=\frac{K\bar b}{S_y},\qquad n=\frac{1}{\sqrt{4\nu t}},\qquad \bar b=\frac{h_i+h_m(t)}{2}
$$
