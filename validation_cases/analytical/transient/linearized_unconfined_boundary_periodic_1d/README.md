# Linearized Unconfined Boundary Periodic 1D

Transient synthetic case that validates the propagation of a tide into an
unconfined aquifer against the Ferris (1951) solution:

- a west-side Dirichlet boundary, the sea, that follows a tide record,
- a fixed east-side head, 8.4 damping lengths inland,
- no recharge,
- a homogeneous 1D aquifer.

Numerical setup:

- geometry: quasi-1D Cartesian grid (`50 x 5` cells of 2 m, single layer),
- flow regime: transient unconfined flow, 192 hourly stress periods (8 days),
- sea: `h0 + A cos(2 pi t / t0)` with `h0 = 10 m`, `A = 0.25 m` and
  `t0 = 24 h`, read from `west_head_tide.csv` as hourly means
  (`aggregate = "mean"`), the launcher route of any side head chronicle,
- aquifer: `K = 1e-4 m/s`, `Sy = 0.2`, saturated thickness 10 m,
- initial condition: uniform `10.0 m`; the run starts at high tide,
- simulated observable: `watertable_elevation`.

Comparison:

- compared quantity: the head profile matrix over the last four tides, once
  the start-up transient has died. Starting at high tide leaves the transient
  no first moment: it decays as `t^-2` and is `4.3e-4 A` (0.1 mm) after four
  tides, against `9.6e-3 A` for a start at mean sea level, which decays as
  `t^-1`,
- the tide in each column: a least-squares harmonic fit over the four tides
  gives its amplitude and its lag behind the sea. A straight line through
  `ln(amplitude)` and through the lag, from one column inland to where the
  reference keeps 5 % of the tide, gives the decay length and the lag length
  of the Ferris method. Both are `sqrt(t0 T / (pi S)) = 11.73 m`,
- boundary position: the sea head is posed where the model holds it, at the
  centre of the boundary column, at the mean centroid of the boundary
  triangles on the triangle strip, on the face nodes of the Voronoi dual
  (`validation_cases/shared/strip_geometry.py`).

The sea column holds the mean tide of each hour. At an output time it lags
the tide by half an hour: up to `A w dt / 2 = 3.3e-2 m`, the largest error of
the case. One backward-Euler step a period, 24 a tide, shortens the decay
length and stretches the lag length by about `w dt / 4 = 6.5 %`.

Direct execution:

```bash
python -m validation_cases.analytical.transient.linearized_unconfined_boundary_periodic_1d.run_case
```

The irregular strip bundle is rebuilt with
`python -m validation_cases.analytical.transient.linearized_unconfined_boundary_periodic_1d.mesh_bundle`.

Reference used by the documentation:

- reference: Ferris (1951) tidal propagation into a semi-infinite linearized
  unconfined aquifer, `T = K b` with the saturated thickness `b`, `S = Sy`

## Equations

The equations of the reference solution the comparison uses.

$$
S_y\frac{\partial h}{\partial t}=T\frac{\partial^2 h}{\partial x^2},\qquad h(0,t)=h_0+A\cos\left(\frac{2\pi t}{t_0}\right)
$$

$$
h(x,t)=h_0+A\,e^{-x/\lambda}\cos\left(\frac{2\pi t}{t_0}-\frac{x}{\lambda}\right),\qquad \lambda=\sqrt{\frac{t_0\,T}{\pi\,S_y}}
$$
