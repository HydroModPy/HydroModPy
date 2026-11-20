# Rotated K tensor, plan view

Steady confined flow along a strip whose horizontal K tensor is turned off the
grid axes by `[flow.param.angle1]`, with `[flow.param.K22]` ten times smaller
than K. It checks the whole chain of the tensor: the HydroModPy configuration,
the NPF arrays, MODFLOW 6 with XT3D and the stored heads and flows.

Setup:

- strip of 1000 x 50 m in 5 m cells, one confined layer of 10 m, heads of 110 m
  on the west end and 100 m on the east end, no flow on the north and south
  sides, no recharge,
- K11 = 1e-4 m/s, K22 = 1e-5 m/s, ANGLE1 = +30 deg (`modflow6`) and -30 deg
  (`modflow6_mirrored`), each against its own reference,
- XT3D on by the HydroModPy rule: K22 differs from K and ANGLE1 is not a
  multiple of 90 deg,
- a linear solve without damping, closed at 1e-9 m (`config_common.toml`).

Comparison:

- simulated observable: `head` and the `constant_head` budget of the run store
- reference: exact uniform flow of the rotated tensor, read in a window of
  +/- 100 m around the middle of the strip
- compared quantities: the direction of the head gradient, the heads against
  the plane of that direction whose level and slope along the strip are fitted,
  and the flows into the west end and out of the east end

The ends hold one head over the whole width, which the rotated tensor does not
carry, so the head bends near them. These end effects decay over
`l = w sqrt(det K) / (pi K_yy) = 15.5 m` and lie 22 decay lengths short of the
window. Their size sets the slope along the strip, which has no closed form and
is fitted. A sign error on ANGLE1 flips the slope across the strip (a 0.56 m
drop over the window), an axis error changes it, and without XT3D it stays at
zero.

Not validated: unstructured meshes (the patch test covers XT3D there for an
isotropic K), a heterogeneous tensor, a well in the rotated aquifer.

Direct execution:

```bash
python -m validation_cases.analytical.steady.k_tensor_rotated_plan_2d.run_case --no-show
python -m validation_cases.analytical.steady.k_tensor_rotated_plan_2d.run_case --solver modflow6_mirrored --no-show
```

## Equations

MODFLOW 6 turns the K11 axis by ANGLE1 = a from +x toward +y (Langevin et al.,
2017, USGS TM 6-A55), so the tensor reads in the plane

$$
K_{xx}=K_{11}\cos^2 a+K_{22}\sin^2 a,\quad
K_{yy}=K_{11}\sin^2 a+K_{22}\cos^2 a,\quad
K_{xy}=\left(K_{11}-K_{22}\right)\sin a\cos a
$$

Far from the ends no water crosses the sides, so the exact head is a plane with

$$
\frac{\partial h/\partial y}{\partial h/\partial x}=-\frac{K_{xy}}{K_{yy}},\qquad
Q=\frac{K_{11}K_{22}}{K_{yy}}\left(-\frac{\partial h}{\partial x}\right)w\,b
$$

where $Q$ is the flow along the strip, $w$ its width and $b$ its thickness.
